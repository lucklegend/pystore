import hmac

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.serializers import AuthTokenSerializer
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import HandoffCode
from .serializers import HandoffRedeemSerializer, HandoffRequestSerializer, RegisterSerializer, UserSerializer
from .services import mint_code, redeem_code, sign_out_everywhere

# One message for every unusable code, so a caller cannot tell unknown, expired, used and mismatched apart.
INVALID_HANDOFF = "This sign-in code is invalid or has expired."


def has_client_secret(request: Request) -> bool:
    """True when the caller presents shop-web's SSO client secret."""
    presented = request.headers.get("X-SSO-Client-Secret", "").encode()
    expected = settings.SSO_CLIENT_SECRET.encode()
    # An empty configured secret must not let an empty header through.
    return bool(expected) and hmac.compare_digest(presented, expected)


class UnverifiedCallerThrottle:
    """Rate-limit, per client IP, only callers without the client secret.

    shop-web redeems every user's code from its one address, so throttling it by IP would cap
    sign-ins site-wide and let anyone sharing that address use the allowance up. Guessing the
    secret is what the limit is for; a caller holding it is trusted with codes anyway.
    """

    def __init__(self) -> None:
        self.by_ip = ScopedRateThrottle()

    def allow_request(self, request: Request, view: APIView) -> bool:
        return has_client_secret(request) or self.by_ip.allow_request(request, view)

    def wait(self) -> float | None:
        return self.by_ip.wait()


def token_response(user, status_code: int) -> Response:
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": UserSerializer(user).data}, status=status_code)


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return token_response(user, status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request: Request) -> Response:
        serializer = AuthTokenSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return token_response(serializer.validated_data["user"], status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request) -> Response:
        sign_out_everywhere(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class HandoffView(APIView):
    """The storefront, as issuer, mints a code that signs its logged-in user into the CMS."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = HandoffRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ttl = settings.SSO_CODE_TTL_SECONDS
        # mint_code raises Django's PermissionDenied for a user who may not use the CMS; DRF answers it with 403.
        code = mint_code(request.user, HandoffCode.Audience.CMS, serializer.validated_data["state"], ttl=ttl)
        return Response({"code": code, "expires_in": ttl}, status=status.HTTP_201_CREATED)


class HandoffRedeemView(APIView):
    """The storefront, as consumer, trades a code from the CMS for the user's token, server to server."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [UnverifiedCallerThrottle]
    throttle_scope = "sso"

    def post(self, request: Request) -> Response:
        if not has_client_secret(request):
            raise PermissionDenied
        serializer = HandoffRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = redeem_code(
            serializer.validated_data["code"], HandoffCode.Audience.STOREFRONT, serializer.validated_data["state"]
        )
        if user is None:
            return Response({"detail": INVALID_HANDOFF}, status=status.HTTP_400_BAD_REQUEST)
        return token_response(user, status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)
