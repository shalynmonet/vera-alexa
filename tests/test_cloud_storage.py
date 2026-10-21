"""vera/cloud_storage.py is entirely optional -- every function must behave
safely when VERA_S3_BUCKET isn't set (the default for a laptop demo),
and correctly hand back a presigned URL when it is."""
from vera import cloud_storage, family


def test_disabled_when_no_bucket(monkeypatch):
    monkeypatch.setattr(cloud_storage, "BUCKET", None)
    cloud_storage.object_exists.cache_clear()
    assert not cloud_storage.enabled()
    assert cloud_storage.presigned_url("media/exercise/a.mp4") is None
    assert cloud_storage.object_exists("media/exercise/a.mp4") is False
    cloud_storage.object_exists.cache_clear()


def test_upload_bytes_refuses_when_disabled(monkeypatch):
    monkeypatch.setattr(cloud_storage, "BUCKET", None)
    try:
        cloud_storage.upload_bytes("cheers/a.webm", b"x", "audio/webm")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


class _FakeS3:
    def __init__(self):
        self.put = []

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://fake-bucket.s3.amazonaws.com/{Params['Key']}?sig=abc&expires={ExpiresIn}"

    def head_object(self, Bucket, Key):
        if Key != "media/exercise/real.mp4":
            raise cloud_storage.ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")

    def put_object(self, Bucket, Key, Body, ContentType):
        self.put.append((Bucket, Key, Body, ContentType))


def test_enabled_with_bucket(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(cloud_storage, "BUCKET", "fake-bucket")
    monkeypatch.setattr(cloud_storage, "PREFIX", "")
    monkeypatch.setattr(cloud_storage, "_client", fake)
    cloud_storage.object_exists.cache_clear()

    assert cloud_storage.enabled()
    assert cloud_storage.object_exists("media/exercise/real.mp4")
    assert not cloud_storage.object_exists("media/exercise/missing.mp4")

    url = cloud_storage.presigned_url("cheers/a.webm", expires_in=60)
    assert url == "https://fake-bucket.s3.amazonaws.com/cheers/a.webm?sig=abc&expires=60"

    cloud_storage.upload_bytes("cheers/a.webm", b"hello", "audio/webm")
    assert fake.put == [("fake-bucket", "cheers/a.webm", b"hello", "audio/webm")]
    cloud_storage.object_exists.cache_clear()


def test_cheer_media_url_only_for_s3_storage():
    assert family.cheer_media_url({"storage": "local", "file": "a.webm"}) is None
    assert family.cheer_media_url({"storage": "s3", "file": "a.webm"}) is None  # no bucket configured in this process
