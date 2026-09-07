from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from .models import AuditLog
@receiver(user_logged_in)
@receiver(user_logged_out)
@receiver(user_login_failed)
def authentication_event(sender, request=None, user=None, signal=None, **kwargs):
    action = 'login' if signal is user_logged_in else 'logout' if signal is user_logged_out else 'login_failed'
    AuditLog.objects.create(actor=user, action=action, outcome='denied' if action == 'login_failed' else 'success')
