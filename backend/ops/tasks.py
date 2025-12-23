from celery import shared_task
from django.utils import timezone
from .models import Heartbeat
import os, subprocess, tempfile, datetime, boto3
from celery import shared_task

@shared_task
def beat_heartbeat():
    Heartbeat.objects.update_or_create(key="beat", defaults={"seen_at": timezone.now()})
    return "ok"

def _mysqldump_to_file(path: str):
    host = os.getenv("MYSQL_HOST") or os.getenv("DB_HOST") or "127.0.0.1"
    if host == "db":
        host = "127.0.0.1"


    port = os.getenv("MYSQL_PORT","3306")
    db = os.getenv("MYSQL_DATABASE","nutrilift")
    user = os.getenv("MYSQL_USER","nutrilift")
    pwd = os.getenv("MYSQL_PASSWORD","nutrilift")
    cmd = [
        "mysqldump", f"-h{host}", f"-P{port}", f"-u{user}", f"-p{pwd}",
        "--single-transaction", "--routines", "--triggers", "--events",
        db
    ]
    with open(path, "wb") as f:
        subprocess.check_call(cmd, stdout=f)

@shared_task
def nightly_backup():
    bucket = os.getenv("AWS_S3_BACKUP_BUCKET")
    if not bucket:
        return "no bucket configured"
    with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
        _mysqldump_to_file(tmp.name)
        key = f"db/{datetime.datetime.utcnow().strftime('%Y-%m-%d')}.sql"
        s3 = boto3.client("s3", region_name=os.getenv("AWS_DEFAULT_REGION"))
        s3.upload_file(tmp.name, bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"})
    return f"s3://{bucket}/{key}"
