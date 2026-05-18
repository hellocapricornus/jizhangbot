# handlers/address_image.py
import io
import os
from PIL import Image, ImageDraw, ImageFont
from logger import bot_logger as logger

BG_IMAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'bg_address.png')


def generate_address_image(address: str, chain_type: str = 'TRC20') -> bytes:
    try:
        # 加载背景图
        if os.path.exists(BG_IMAGE_PATH):
            img = Image.open(BG_IMAGE_PATH).convert('RGBA')
        else:
            logger.warning(f"背景图不存在: {BG_IMAGE_PATH}，使用纯色背景")
            img = Image.new('RGBA', (900, 120), color=(18, 25, 45, 255))

        draw = ImageDraw.Draw(img)
        img_width, img_height = img.size

        # ========== 字体（改大） ==========
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        except:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
            except:
                font = ImageFont.load_default()

        # 计算文字尺寸
        bbox = draw.textbbox((0, 0), address, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # 文字位置（居中）
        padding_x = 30
        padding_y = 15
        bg_x1 = (img_width - text_width) // 2 - padding_x
        bg_y1 = (img_height - text_height) // 2 - padding_y
        bg_x2 = (img_width + text_width) // 2 + padding_x
        bg_y2 = (img_height + text_height) // 2 + padding_y

        # ========== 画半透明底色 ==========
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle(
            [bg_x1, bg_y1, bg_x2, bg_y2],
            radius=12,
            fill=(0, 0, 0, 160)  # 黑色半透明，改最后一个数字调透明度
        )
        img = Image.alpha_composite(img, overlay)

        # ========== 画文字 ==========
        draw = ImageDraw.Draw(img)
        text_x = (img_width - text_width) // 2
        text_y = (img_height - text_height) // 2
        draw.text((text_x, text_y), address, fill=(255, 255, 255, 255), font=font)

        # 转 RGB 用于发送
        rgb_img = img.convert('RGB')
        output = io.BytesIO()
        rgb_img.save(output, format='PNG')
        output.seek(0)
        return output.getvalue()

    except Exception as e:
        logger.error(f"[地址图片] 生成失败: {e}", exc_info=True)
        return None
