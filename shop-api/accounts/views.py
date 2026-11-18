from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.serializers import AuthTokenSerializer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RegisterSerializer, UserSerializer


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
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)
