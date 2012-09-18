from django.conf.urls.defaults import patterns, url


urlpatterns = patterns("notification.views",
    url(r"^$", "notice_list", name="notification_notices"),
    url(r"^settings/$", "notice_settings", name="notification_notice_settings"),
    url(r"^(\d+)/$", "notice_detail", name="notification_notice"),
    url(r"^feed/$", "notice_feed", name="notification_feed_for_user"),
    url(r"^mark_all_seen/$", "mark_all_seen", name="notification_mark_all_seen"),
)
