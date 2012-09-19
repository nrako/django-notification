from __future__ import with_statement

from celery.task import task


@task(ignore_result=True)
def notify(users, label, extra_context=None, on_site=True, sender=None,
           from_email=None, headers=None):
    """
    Creates a new notice.

    You can pass in on_site=False to prevent the notice emitted from being
    displayed on the site.
    """
    from notification.models import Notice
    from notification.utils import context_language

    for user in users:
        with context_language(user):
            notice = Notice.objects.create_notice(user, label, extra_context,
                                                  on_site, sender)
            notice.send(notice, extra_context, from_email, headers)
