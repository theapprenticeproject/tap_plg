#!/usr/bin/env python3
"""
Download CLIP models for offline use in MentorMe

Usage:
    python scripts/download_clip_model.py --model ViT-L-14
    python scripts/download_clip_model.py --model ViT-B-32
    python scripts/download_clip_model.py --all
"""

import argparse
import os
import sys
from pathlib import Path
import logging

# per-file logger
logger = logging.getLogger(__name__)

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    logger.error("huggingface_hub not installed")
    logger.error("Install with: pip install huggingface_hub")
    sys.exit(1)


MODELS = {
    "ViT-L-14": {
        "repo_id": "laion/CLIP-ViT-L-14-laion2B-s32B-b82K",
        "filename": "open_clip_pytorch_model.bin",
        "size_mb": 890,
        "description": "Large model, highest accuracy, ~900MB",
    },
    "ViT-B-32": {
        "repo_id": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
        "filename": "open_clip_pytorch_model.bin",
        "size_mb": 350,
        "description": "Smaller model, good balance, ~350MB",
    },
    "ViT-B-16": {
        "repo_id": "laion/CLIP-ViT-B-16-laion2B-s34B-b88K",
        "filename": "open_clip_pytorch_model.bin",
        "size_mb": 350,
        "description": "Smaller model, slightly slower, ~350MB",
    },
}


def download_model(model_name, base_dir="./models/clip"):
    """Download a CLIP model from HuggingFace Hub"""
    if model_name not in MODELS:
        logger.error("Unknown model requested", extra={"model": model_name})
        logger.info("Available models", extra={"models": list(MODELS.keys())})
        return False

    config = MODELS[model_name]
    local_dir = os.path.join(base_dir, model_name)

    logger.info(
        "download_start",
        extra={
            "model": model_name,
            "description": config["description"],
            "repo": config["repo_id"],
            "file": config["filename"],
            "target_dir": local_dir,
        },
    )

    # Create directory
    os.makedirs(local_dir, exist_ok=True)

    try:
        logger.info("hf_connecting", extra={"repo": config["repo_id"]})
        logger.info("download_progress_start", extra={"approx_mb": config["size_mb"]})

        model_path = hf_hub_download(
            repo_id=config["repo_id"],
            filename=config["filename"],
            local_dir=local_dir,
            local_dir_use_symlinks=False,
            resume_download=True,
        )

        logger.info("download_verifying", extra={"model_path": model_path})

        # Verify file size
        if os.path.exists(model_path):
            size_mb = os.path.getsize(model_path) / (1024 * 1024)
            logger.info(
                "download_success",
                extra={
                    "model": model_name,
                    "location": os.path.abspath(model_path),
                    "size_mb": f"{size_mb:.2f}",
                },
            )
            logger.info(
                "download_instructions",
                extra={
                    "env_updates": {
                        "CLIP_MODEL": model_name,
                        "CLIP_LOCAL_MODEL_PATH": model_path,
                    }
                },
            )
            return True
        else:
            logger.error("download_failed_no_file", extra={"model": model_name})
            return False

    except KeyboardInterrupt:
        logger.warning("download_cancelled_by_user", extra={"model": model_name})
        logger.info(
            "resume_instruction",
            extra={"cmd": f"python {sys.argv[0]} --model {model_name}"},
        )
        return False
    except Exception as e:
        logger.error("download_failed", extra={"model": model_name, "error": str(e)})
        logger.info(
            "download_troubleshooting",
            extra={
                "steps": [
                    "Check internet connection",
                    "Verify HuggingFace Hub is accessible",
                    "Try setting DISABLE_SSL_VERIFY=true if behind corporate proxy",
                    f"Check available disk space (~{config['size_mb']}MB required)",
                ]
            },
        )
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download CLIP models for offline use in MentorMe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Download recommended model:
    python scripts/download_clip_model.py --model ViT-L-14
  
  Download smaller model for testing:
    python scripts/download_clip_model.py --model ViT-B-32
  
  Download all models:
    python scripts/download_clip_model.py --all

Available Models:
  ViT-L-14  - Large model, highest accuracy (~900MB)
  ViT-B-32  - Balanced model, good performance (~350MB)
  ViT-B-16  - Balanced model, slightly slower (~350MB)
        """,
    )

    parser.add_argument(
        "--model", type=str, choices=list(MODELS.keys()), help="Model to download"
    )

    parser.add_argument(
        "--all", action="store_true", help="Download all available models"
    )

    parser.add_argument(
        "--dir",
        type=str,
        default="./models/clip",
        help="Base directory for models (default: ./models/clip)",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.model and not args.all:
        parser.print_help()
        logger.error("No model specified - use --model or --all")
        sys.exit(1)

    # Download models
    if args.all:
        logger.info("download_all_start", extra={"count": len(MODELS)})
        success_count = 0
        for model_name in MODELS.keys():
            if download_model(model_name, args.dir):
                success_count += 1
        logger.info(
            "download_all_summary",
            extra={"success_count": success_count, "total": len(MODELS)},
        )
        sys.exit(0 if success_count == len(MODELS) else 1)
    else:
        success = download_model(args.model, args.dir)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
