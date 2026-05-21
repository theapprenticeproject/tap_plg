from .image_processor import ImageProcessor


async def get_processor(
    data: dict, db_manager=None, image_processor=None
):
    """
    Returns appropriate processor based on content type.
    Priority: if submission_type is 'image' → ImageProcessor
    """
    if data.get("submission_type") == "image":
        return image_processor
    return None
