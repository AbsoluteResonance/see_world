#!/usr/bin/env python3
"""CLI tool for Kimi multi-modal understanding."""

import argparse
import json
import sys

from kimi_client import KimiClient, KimiAPIError


def main():
    parser = argparse.ArgumentParser(description="Kimi multi-modal understanding CLI")
    parser.add_argument("--image", help="Path to a single image")
    parser.add_argument("--images", nargs="+", help="Paths to multiple images")
    parser.add_argument("--video", help="Path to a video file")
    parser.add_argument("--prompt", default="请详细描述内容", help="Analysis prompt")
    parser.add_argument("--stream", action="store_true", help="Enable streaming output")
    parser.add_argument("--model", default="kimi-k2.6", help="Kimi model name")
    parser.add_argument("--api-key", help="Kimi API key (default: KIMI_API_KEY env var)")
    args = parser.parse_args()

    if not args.image and not args.images and not args.video:
        parser.error("Provide at least one of --image, --images, or --video")

    try:
        client = KimiClient(api_key=args.api_key, model=args.model)
    except KimiAPIError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    try:
        if args.image:
            result = client.understand_image(args.image, args.prompt)
        elif args.images:
            result = client.understand_images(args.images, args.prompt)
        elif args.video:
            result = client.understand_video(args.video, args.prompt)
        else:
            result = {"error": "No input provided"}
    except KimiAPIError as e:
        result = {"error": str(e)}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
