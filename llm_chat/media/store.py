"""Where media files live: a private S3 bucket, or a local folder in development.

CLOZE_MEDIA_BUCKET picks S3. Without it, development and tests use a folder
under instance/; production has no store at all, so uploads are switched off
rather than written to a container disk that disappears on the next deploy.

Both stores serve a file the same way: the caller has already checked that the
viewer may see it. S3 answers with a redirect to a short-lived presigned URL,
so file bytes never pass through the app and video seeking (range requests)
goes straight to S3. Pages only ever link to /media/<public_id>, never to a
storage URL, so how files are delivered can change (e.g. to CloudFront)
without touching saved content.
"""
import os

from flask import current_app, redirect, send_file

# How long a cached redirect may be reused by the browser. Presigned URLs live
# longer than this, so a cached redirect never points at an expired URL.
REDIRECT_CACHE_SECONDS = 300


class LocalStore:
    """Files under a local folder. Development and tests only."""

    def __init__(self, root):
        self.root = os.path.realpath(root)

    def _path(self, key):
        path = os.path.realpath(os.path.join(self.root, key))
        # Keys are built by the server, but never let one escape the folder.
        if not path.startswith(self.root + os.sep):
            raise ValueError(f"Storage key escapes the media folder: {key!r}")
        return path

    def put(self, key, data, content_type):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)

    def serve(self, rendition, expires_in):
        response = send_file(self._path(rendition.storage_key), mimetype=rendition.content_type,
                             conditional=True, max_age=REDIRECT_CACHE_SECONDS)
        response.cache_control.public = False
        response.cache_control.private = True
        # Served from our own origin here, so make sure the file can never act as a page.
        response.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
        return response


class S3Store:
    """A private S3 bucket. Encryption at rest is the bucket's default (KMS)."""

    def __init__(self, bucket, client):
        self.bucket = bucket
        self.client = client

    def put(self, key, data, content_type):
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type,
            CacheControl=f'private, max-age={REDIRECT_CACHE_SECONDS}',
        )

    def presigned_url(self, rendition, expires_in):
        return self.client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': self.bucket,
                'Key': rendition.storage_key,
                'ResponseContentType': rendition.content_type,
            },
            ExpiresIn=expires_in,
        )

    def serve(self, rendition, expires_in):
        response = redirect(self.presigned_url(rendition, expires_in), code=302)
        response.headers['Cache-Control'] = f'private, max-age={REDIRECT_CACHE_SECONDS}'
        return response


def _s3_client(region):
    import boto3
    from botocore.config import Config
    # SigV4 is required to read KMS-encrypted objects through a presigned URL.
    return boto3.client('s3', region_name=region,
                        config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'}))


def get_store():
    """The configured store, or None when uploads are switched off (production without a bucket)."""
    app = current_app
    cached = app.extensions.get('cloze_media_store')
    if cached is not None:
        return cached or None

    bucket = app.config.get('CLOZE_MEDIA_BUCKET')
    if bucket:
        store = S3Store(bucket, _s3_client(app.config.get('CLOZE_MEDIA_REGION')))
    elif app.config.get('PRODUCTION'):
        store = False
    else:
        root = app.config.get('MEDIA_LOCAL_DIR') or os.path.join(app.instance_path, 'media')
        store = LocalStore(root)
    app.extensions['cloze_media_store'] = store
    return store or None
