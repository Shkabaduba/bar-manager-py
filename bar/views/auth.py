from django.contrib.auth.views import LoginView


class BarLoginView(LoginView):
    """Custom login view redirecting already authenticated staff."""

    template_name = "registration/login.html"
    redirect_authenticated_user = True
