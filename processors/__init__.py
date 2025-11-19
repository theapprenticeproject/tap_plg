from .text_processor import TextProcessor
from .image_processor import ImageProcessor


async def get_processor(
    data: dict, db_manager=None, image_processor=None, text_processor=None
):
    """
    Returns appropriate processor based on content type.
    Priority: if 'img_url' present → ImageProcessor
    otherwise → TextProcessor
    """
    if data.get("img_url"):
        return image_processor
    elif data.get("text"):
        return text_processor
    return None
