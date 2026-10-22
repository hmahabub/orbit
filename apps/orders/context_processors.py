from .models import SupplierPO


def approvals(request):
    """Number of supplier POs waiting for approval, for the staff menu badge."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or not (user.is_staff or user.is_superuser):
        return {}
    return {'pending_approvals': SupplierPO.objects.filter(approval='pending').count()}
