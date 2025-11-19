import open_clip as clip
import torch
from PIL import Image
import logging
import numpy as np
from typing import Optional, Any, Tuple, Union
import os
import ssl

logger = logging.getLogger(__name__)


class CLIPHandler:
    """
    CLIP model handler for generating image embeddings
    Uses OpenAI's CLIP ViT-L-14 model
    """

    def __init__(
        self,
        model_name: str = "ViT-L-14",
        device: Optional[str] = None,
        pretrained: str = "laion2B-s32B-b82K",
        local_model_path: Optional[str] = None,
    ):
        """
        Args:
            model_name: CLIP model variant (default: ViT-L-14)
            device: "cuda" for GPU or "cpu", auto-detect if None
            pretrained: pretrained weights to use (default: laion2B-s32B-b82K)
            local_model_path: Path to locally downloaded model weights (e.g., ./models/clip/open_clip_pytorch_model.bin)
                            If provided, this takes precedence over downloading from HuggingFace
        """
        self.model_name = model_name
        self.device = (
            device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.local_model_path = local_model_path

        if os.getenv("DISABLE_SSL_VERIFY", "false").lower() == "true":
            logger.warning("SSL verification disabled for HuggingFace downloads")
            import ssl

            ssl._create_default_https_context = ssl._create_unverified_context

        try:
            logger.info(
                f"Loading open_clip model: {model_name} on {self.device} (pretrained={pretrained})..."
            )

            created: Optional[Union[Tuple[Any, Any, Any], Tuple[Any, Any]]] = None

            # Try to use local model path directly with open_clip
            if local_model_path and os.path.exists(local_model_path):
                logger.info(
                    f"Attempting to load model from local path: {local_model_path}"
                )
                try:
                    # Method 1: Try passing local path directly to pretrained parameter
                    created = clip.create_model_and_transforms(
                        model_name, pretrained=local_model_path
                    )
                    logger.info(
                        f"Successfully loaded model from local path: {local_model_path}"
                    )
                except Exception as method1_error:
                    logger.warning(
                        f"Method 1 (direct path) failed: {method1_error}"
                    )
                    try:
                        # Method 2: Load checkpoint manually
                        logger.info("Trying manual checkpoint loading...")
                        model_only = clip.create_model(model_name)
                        model_temp, preprocess_train, preprocess_val = (
                            clip.create_model_and_transforms(model_name, pretrained=None)
                        )

                        checkpoint: Any = torch.load(local_model_path, map_location=self.device, weights_only=False)

                        if "state_dict" in checkpoint:
                            model_only.load_state_dict(checkpoint["state_dict"])
                        elif "model" in checkpoint:
                            model_only.load_state_dict(checkpoint["model"])
                        else:
                            model_only.load_state_dict(checkpoint)

                        created = (model_only, preprocess_train, preprocess_val)
                        logger.info(
                            f"Successfully loaded model from local path (method 2): {local_model_path}"
                        )
                    except Exception as method2_error:
                        logger.warning(
                            f"Method 2 (manual load) failed: {method2_error}"
                        )
                        logger.info("Falling back to downloading from HuggingFace...")
                        created = None
            elif local_model_path:
                logger.warning(
                    f"Local model path specified but file not found: {local_model_path}"
                )
                logger.info("Falling back to downloading from HuggingFace...")

            # Download from HuggingFace if no local model was loaded
            if created is None:
                logger.info(f"Downloading model from HuggingFace (pretrained={pretrained})...")
                try:
                    created = clip.create_model_and_transforms(
                        model_name, pretrained=pretrained
                    )
                    logger.info(f"Successfully loaded model with pretrained='{pretrained}'")
                except Exception as download_error:
                    raise RuntimeError(
                        f"Failed to load CLIP model. Local model not found at '{local_model_path}' "
                        f"and remote download failed with pretrained='{pretrained}': {download_error}"
                    ) from download_error

            if created and len(created) == 3:
                self.model, _, self.preprocess = created  # type: ignore[misc]
            elif created:
                self.model, self.preprocess = created  # type: ignore[misc]
            else:
                raise RuntimeError("Failed to initialize CLIP model and transforms")

            try:
                self.model.to(self.device)  # type: ignore[attr-defined]
            except Exception:
                pass

            self.model.eval()  # type: ignore[attr-defined]
            logger.info(f"open_clip model loaded successfully on {self.device}")

        except Exception as e:
            logger.error(f"Failed to load CLIP model: {e}")
            raise

    def generate_embedding(self, image: Image.Image) -> np.ndarray:
        """
        Generate CLIP embedding for an image

        Args:
            image: PIL Image object

        Returns:
            numpy array of shape (512,) - normalized embedding vector
        """
        try:
           
            image_tensor = self.preprocess(image).unsqueeze(0).to(self.device)  # type: ignore[operator, attr-defined]

           
            with torch.no_grad():
                image_features = self.model.encode_image(image_tensor)  # type: ignore[operator]

                image_features = image_features / image_features.norm(
                    dim=-1, keepdim=True
                )

            embedding = image_features.cpu().numpy().flatten()

            logger.debug(
                f"Generated CLIP embedding: shape={embedding.shape}, norm={np.linalg.norm(embedding):.4f}"
            )

            return embedding

        except Exception as e:
            logger.error(f"Failed to generate CLIP embedding: {e}")
            raise

    def compute_similarity(
        self, embedding1: np.ndarray, embedding2: np.ndarray
    ) -> float:
        """
        Compute cosine similarity between two embeddings

        Args:
            embedding1: First embedding (512D vector)
            embedding2: Second embedding (512D vector)

        Returns:
            Similarity score between 0 and 1
        """
        try:
            similarity = np.dot(embedding1, embedding2)

            similarity = np.clip(similarity, 0, 1)

            return float(similarity)

        except Exception as e:
            logger.error(f"Failed to compute similarity: {e}")
            return 0.0

    def get_model_info(self) -> dict:
        """
        Get information about the loaded CLIP model

        Returns:
            dict with model details
        """
        embedding_dim = 512
        try:
            visual_obj = getattr(self.model, "visual", None)
            clip_obj = getattr(self.model, "clip", None)

            if visual_obj is not None and hasattr(visual_obj, "output_dim"):
                embedding_dim = int(visual_obj.output_dim)
            elif clip_obj is not None and hasattr(clip_obj, "output_dim"):
                embedding_dim = int(clip_obj.output_dim)
            else:
                
                embedding_dim = int(getattr(self.model, "embed_dim", embedding_dim))
        except Exception:
            try:
                
                embedding_dim = int(getattr(self.model, "embed_dim", embedding_dim))
            except Exception:
                embedding_dim = 512

        input_resolution = 224
        try:
            # best-effort: if preprocess has 'size' attribute or a transforms.Resize, ignore complexity and keep default
            pass
        except Exception:
            input_resolution = 224

        return {
            "model_name": self.model_name,
            "device": self.device,
            "embedding_dim": embedding_dim,
            "input_resolution": input_resolution,
        }
