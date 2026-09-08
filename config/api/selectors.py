from django.db.models import Q, Sum
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from .models import Location

def require(user, permission):
    if not user.has_perm(permission):
        raise PermissionDenied

def scoped(model, user, write=False):
    qs = model.objects.all()
    perm = 'manage_all_marketing' if write else 'view_all_marketing'
    return qs if user.has_perm('api.' + perm) else qs.filter(marketer=user)

def locations(user):
    qs = Location.objects.filter(active=True)
    return qs if user.has_perm('api.manage_all_marketing') else qs.filter(Q(creator=None)|Q(creator=user))

def eligible_users(user):
    qs = get_user_model().objects.filter(is_active=True)
    if not user.has_perm('api.assign_marketer'):
        return qs.filter(pk=user.pk)
    return qs.filter(Q(groups__permissions__codename='add_customer')|Q(user_permissions__codename='add_customer')|Q(is_superuser=True)).distinct()

def total(qs):
    from decimal import Decimal
    return qs.aggregate(value=Sum('amount'))['value'] or Decimal('0.00')


def location_descendants(user, root):
    """Include the selected location and permitted descendants (five levels)."""
    ids = [root.pk]
    frontier = ids
    for _ in range(4):
        frontier = list(locations(user).filter(parent_id__in=frontier).values_list('pk', flat=True))
        if not frontier:
            break
        ids.extend(frontier)
    return ids
