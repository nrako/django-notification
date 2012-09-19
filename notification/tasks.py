from celery.task import task


@task(ignore_result=True)
def notify(*args, **kwargs):
    from notification.api import send_now
    send_now(*args, **kwargs)
