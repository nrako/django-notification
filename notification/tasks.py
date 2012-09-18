from celery.task import task


@task(ignore_result=True)
def send_notice(*args, **kwargs):
    from notification.api import send_now
    send_now(*args, **kwargs)
