import os
import hashlib
import boto3
from dotenv import load_dotenv
from pathlib import Path
from botocore.exceptions import ClientError, NoCredentialsError

load_dotenv()

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET_NAME")
S3_PREFIX = os.getenv("S3_PREFIX", "")  # optional folder prefix inside the bucket
OUTPUT_DIR = Path(os.getenv("S3_OUTPUT_DIR", "s3_downloads"))


def local_file_matches_object(local_path: Path, obj: dict) -> bool:
    if not local_path.exists() or local_path.stat().st_size != obj["Size"]:
        return False

    etag = obj.get("ETag", "").strip('"')
    if not etag or "-" in etag:
        return False

    digest = hashlib.md5()
    with local_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == etag


def download_bucket(bucket: str, prefix: str, output_dir: Path):
    if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
        raise ValueError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set in .env")
    if not bucket:
        raise ValueError("S3_BUCKET_NAME must be set in .env")

    s3 = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

    downloaded = 0
    skipped = 0
    latest_key = None
    latest_modified = None

    for page in pages:
        objects = page.get("Contents", [])
        if not objects:
            print("No files found in bucket with the given prefix.")
            return

        for obj in objects:
            key: str = obj["Key"]
            last_modified = obj.get("LastModified")

            if last_modified and (latest_modified is None or last_modified > latest_modified):
                latest_key = key
                latest_modified = last_modified

            # skip "folder" placeholder keys (end with /)
            if key.endswith("/"):
                continue

            # strip the prefix so local paths are relative to output_dir
            relative_key = key[len(prefix):].lstrip("/") if prefix else key
            local_path = output_dir / relative_key

            # create parent dirs
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # ETag is an MD5 for non-multipart S3 objects, so same-size edits are detected.
            if local_file_matches_object(local_path, obj):
                print(f"  skip  {relative_key}  (already exists)")
                skipped += 1
                continue

            print(f"  down  {relative_key}  ({obj['Size'] / 1024:.1f} KB)")
            try:
                s3.download_file(bucket, key, str(local_path))
                downloaded += 1
            except ClientError as e:
                print(f"  ERROR downloading {key}: {e}")

    if latest_key and latest_modified:
        print(f"\nMost recently updated file: {latest_key} (modified at {latest_modified.isoformat()})")

    print(f"\nDone. {downloaded} downloaded, {skipped} skipped -> {output_dir.resolve()}")


if __name__ == "__main__":
    download_bucket(
        bucket=S3_BUCKET,
        prefix=S3_PREFIX,
        output_dir=OUTPUT_DIR,
    )
