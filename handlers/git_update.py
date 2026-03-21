# handlers/git_update.py

import subprocess
import os
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from config import OWNER_ID

# 默认的远程仓库和分支
DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"  # 如果你的默认分支是 master，改成 "master"

def get_git_root():
    """获取 git 仓库根目录"""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def git_pull(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """执行 git pull 更新代码"""
    user_id = update.effective_user.id

    # 只允许超级管理员执行
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ 只有超级管理员可以使用此命令")
        return

    # 发送开始消息
    status_msg = await update.message.reply_text("🔄 正在拉取最新代码...")
    git_root = get_git_root()

    try:
        # 先获取当前分支
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=git_root,
            capture_output=True,
            text=True
        )
        current_branch = branch_result.stdout.strip()

        if not current_branch:
            await status_msg.edit_text("❌ 无法获取当前分支")
            return

        # 检查是否有上游跟踪分支
        tracking_result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', f'{current_branch}@{{upstream}}'],
            cwd=git_root,
            capture_output=True,
            text=True
        )

        # 如果没有上游跟踪分支，需要先设置
        if tracking_result.returncode != 0:
            # 尝试设置上游跟踪分支
            set_upstream = subprocess.run(
                ['git', 'branch', '--set-upstream-to', f'{DEFAULT_REMOTE}/{current_branch}', current_branch],
                cwd=git_root,
                capture_output=True,
                text=True
            )

            if set_upstream.returncode != 0:
                # 如果设置失败，可能分支不存在于远程，尝试从 main/master 拉取
                await status_msg.edit_text(
                    f"⚠️ 当前分支 `{current_branch}` 没有设置上游跟踪\n\n"
                    f"请手动执行以下命令：\n"
                    f"```\ngit branch --set-upstream-to={DEFAULT_REMOTE}/{current_branch}\n```",
                    parse_mode='Markdown'
                )
                return

        # 执行 git pull
        result = subprocess.run(
            ['git', 'pull'],
            cwd=git_root,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            if "Already up to date" in output:
                await status_msg.edit_text("✅ 代码已是最新，无需更新")
            else:
                await status_msg.edit_text(
                    f"✅ 代码更新成功！\n\n"
                    f"```\n{output[:500]}\n```\n"
                    f"⚠️ 请手动重启机器人以使更新生效",
                    parse_mode='Markdown'
                )
        else:
            error = result.stderr.strip()
            await status_msg.edit_text(
                f"❌ 更新失败：\n\n"
                f"```\n{error[:500]}\n```",
                parse_mode='Markdown'
            )
    except subprocess.TimeoutExpired:
        await status_msg.edit_text("❌ 更新超时，请稍后重试")
    except Exception as e:
        await status_msg.edit_text(f"❌ 执行出错：{str(e)}")


async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看 git 状态"""
    user_id = update.effective_user.id

    if user_id != OWNER_ID:
        await update.message.reply_text("❌ 只有超级管理员可以使用此命令")
        return

    status_msg = await update.message.reply_text("🔍 正在检查状态...")
    git_root = get_git_root()

    try:
        # 查看当前分支
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=git_root,
            capture_output=True,
            text=True
        )
        current_branch = branch_result.stdout.strip()

        # 查看远程仓库
        remote_result = subprocess.run(
            ['git', 'remote', '-v'],
            cwd=git_root,
            capture_output=True,
            text=True
        )
        remote_info = remote_result.stdout.strip().split('\n')[0] if remote_result.stdout else "未配置"

        # 查看状态
        status_result = subprocess.run(
            ['git', 'status', '--short'],
            cwd=git_root,
            capture_output=True,
            text=True
        )
        status_output = status_result.stdout.strip()

        # 查看是否有上游跟踪
        tracking_result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', f'{current_branch}@{{upstream}}'],
            cwd=git_root,
            capture_output=True,
            text=True
        )
        has_upstream = tracking_result.returncode == 0
        upstream_branch = tracking_result.stdout.strip() if has_upstream else "未设置"

        # 检查远程更新
        subprocess.run(['git', 'fetch'], cwd=git_root, capture_output=True, text=True)

        # 检查本地和远程的差异
        ahead_behind = subprocess.run(
            ['git', 'rev-list', '--count', f'{current_branch}..{upstream_branch}'] if has_upstream else ['git', 'rev-list', '--count'],
            cwd=git_root,
            capture_output=True,
            text=True
        )

        message = f"📊 **Git 状态**\n\n"
        message += f"🌿 当前分支：`{current_branch}`\n"
        message += f"🔗 远程仓库：`{remote_info[:50]}`\n"
        message += f"📡 上游分支：`{upstream_branch}`\n\n"

        if status_output:
            changed_files = len(status_output.split('\n'))
            message += f"📝 **本地修改：** {changed_files} 个文件有变更\n"
            message += f"```\n{status_output[:300]}\n```\n"
        else:
            message += f"✅ 工作区干净，无本地修改\n\n"

        # 检查是否有远程更新
        if has_upstream:
            # 获取远程更新数量
            behind = subprocess.run(
                ['git', 'rev-list', '--count', f'{upstream_branch}..{current_branch}'],
                cwd=git_root,
                capture_output=True,
                text=True
            )
            behind_count = int(behind.stdout.strip() or 0)

            ahead = subprocess.run(
                ['git', 'rev-list', '--count', f'{current_branch}..{upstream_branch}'],
                cwd=git_root,
                capture_output=True,
                text=True
            )
            ahead_count = int(ahead.stdout.strip() or 0)

            if ahead_count > 0:
                message += f"🔄 远程有 {ahead_count} 个新提交可以拉取\n"
                message += f"💡 使用 `/gitpull` 拉取更新"
            elif behind_count > 0:
                message += f"📤 本地有 {behind_count} 个提交未推送"
            else:
                message += f"✅ 已是最新版本"
        else:
            message += f"⚠️ 未设置上游分支，无法检查远程更新\n"
            message += f"💡 请手动执行：`git branch --set-upstream-to={DEFAULT_REMOTE}/{current_branch}`"

        await status_msg.edit_text(message, parse_mode='Markdown')

    except Exception as e:
        await status_msg.edit_text(f"❌ 检查失败：{str(e)}")


async def git_branch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有分支"""
    user_id = update.effective_user.id

    if user_id != OWNER_ID:
        await update.message.reply_text("❌ 只有超级管理员可以使用此命令")
        return

    status_msg = await update.message.reply_text("🔍 正在获取分支列表...")
    git_root = get_git_root()

    try:
        # 获取所有分支
        branch_result = subprocess.run(
            ['git', 'branch', '-a'],
            cwd=git_root,
            capture_output=True,
            text=True
        )

        branches = branch_result.stdout.strip().split('\n')
        current_branch = None

        # 找出当前分支
        for i, b in enumerate(branches):
            if b.startswith('*'):
                current_branch = b[1:].strip()
                branches[i] = f"✅ `{b[1:].strip()}` (当前)"
            else:
                branches[i] = f"   `{b.strip()}`"

        message = f"📊 **Git 分支列表**\n\n"
        message += "\n".join(branches[:30])  # 最多显示30个

        if len(branches) > 30:
            message += f"\n\n... 还有 {len(branches) - 30} 个分支未显示"

        await status_msg.edit_text(message, parse_mode='Markdown')

    except Exception as e:
        await status_msg.edit_text(f"❌ 获取分支失败：{str(e)}")


def get_git_handlers():
    """返回 git 相关的命令处理器"""
    return [
        CommandHandler("gitpull", git_pull),
        CommandHandler("gitstatus", git_status),
        CommandHandler("gitbranch", git_branch),
    ]
