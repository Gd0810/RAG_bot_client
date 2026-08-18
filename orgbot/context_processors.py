from .models import OrganizationProfile


def organization_profile(request):
    """Makes the organization profile available in every template."""
    try:
        profile = OrganizationProfile.get_solo()
    except Exception:
        profile = None
    return {"org_profile": profile}
