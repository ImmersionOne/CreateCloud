"""AWS Cognito authentication."""

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from crat8cloud.core.models import User

logger = logging.getLogger(__name__)


class AuthClient:
    """Client for AWS Cognito authentication."""

    def __init__(
        self,
        user_pool_id: str,
        client_id: str,
        region: str = "us-east-1",
    ):
        """
        Initialize the auth client.

        Args:
            user_pool_id: Cognito User Pool ID.
            client_id: Cognito App Client ID.
            region: AWS region.
        """
        self.user_pool_id = user_pool_id
        self.client_id = client_id
        self.region = region

        self._cognito = boto3.client("cognito-idp", region_name=region)
        self._current_user: Optional[User] = None
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._id_token: Optional[str] = None

    @property
    def is_authenticated(self) -> bool:
        """Check if user is currently authenticated."""
        return self._access_token is not None

    @property
    def current_user(self) -> Optional[User]:
        """Get the current authenticated user."""
        return self._current_user

    @property
    def access_token(self) -> Optional[str]:
        """Get the current access token."""
        return self._access_token

    def sign_up(self, email: str, password: str, display_name: str) -> dict:
        """
        Register a new user.

        Args:
            email: User email.
            password: User password.
            display_name: Display name.

        Returns:
            Sign up response.
        """
        try:
            response = self._cognito.sign_up(
                ClientId=self.client_id,
                Username=email,
                Password=password,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "name", "Value": display_name},
                ],
            )
            logger.info(f"User signed up: {email}")
            return response

        except ClientError as e:
            logger.error(f"Sign up failed: {e}")
            raise AuthError(str(e)) from e

    def confirm_sign_up(self, email: str, confirmation_code: str) -> dict:
        """
        Confirm user registration with verification code.

        Args:
            email: User email.
            confirmation_code: Verification code from email.

        Returns:
            Confirmation response.
        """
        try:
            response = self._cognito.confirm_sign_up(
                ClientId=self.client_id,
                Username=email,
                ConfirmationCode=confirmation_code,
            )
            logger.info(f"User confirmed: {email}")
            return response

        except ClientError as e:
            logger.error(f"Confirmation failed: {e}")
            raise AuthError(str(e)) from e

    def sign_in(self, email: str, password: str) -> User:
        """
        Sign in a user.

        Args:
            email: User email.
            password: User password.

        Returns:
            Authenticated User object.
        """
        try:
            response = self._cognito.initiate_auth(
                ClientId=self.client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={
                    "USERNAME": email,
                    "PASSWORD": password,
                },
            )

            auth_result = response.get("AuthenticationResult", {})
            self._access_token = auth_result.get("AccessToken")
            self._refresh_token = auth_result.get("RefreshToken")
            self._id_token = auth_result.get("IdToken")

            # Get user details
            self._current_user = self._get_user_details()
            logger.info(f"User signed in: {email}")

            return self._current_user

        except ClientError as e:
            logger.error(f"Sign in failed: {e}")
            raise AuthError(str(e)) from e

    def sign_out(self):
        """Sign out the current user."""
        if self._access_token:
            try:
                self._cognito.global_sign_out(AccessToken=self._access_token)
            except ClientError as e:
                logger.warning(f"Sign out API call failed: {e}")

        self._access_token = None
        self._refresh_token = None
        self._id_token = None
        self._current_user = None
        logger.info("User signed out")

    def refresh_tokens(self) -> bool:
        """
        Refresh the access token using the refresh token.

        Returns:
            True if refresh succeeded.
        """
        if not self._refresh_token:
            return False

        try:
            response = self._cognito.initiate_auth(
                ClientId=self.client_id,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={
                    "REFRESH_TOKEN": self._refresh_token,
                },
            )

            auth_result = response.get("AuthenticationResult", {})
            self._access_token = auth_result.get("AccessToken")
            self._id_token = auth_result.get("IdToken")

            logger.info("Tokens refreshed")
            return True

        except ClientError as e:
            logger.error(f"Token refresh failed: {e}")
            self._access_token = None
            self._id_token = None
            return False

    def _get_user_details(self) -> User:
        """Get details for the current authenticated user."""
        if not self._access_token:
            raise AuthError("Not authenticated")

        try:
            response = self._cognito.get_user(AccessToken=self._access_token)

            # Extract attributes
            attributes = {attr["Name"]: attr["Value"] for attr in response.get("UserAttributes", [])}

            return User(
                user_id=attributes.get("sub", ""),
                email=attributes.get("email", ""),
                display_name=attributes.get("name", ""),
            )

        except ClientError as e:
            logger.error(f"Failed to get user details: {e}")
            raise AuthError(str(e)) from e

    def forgot_password(self, email: str) -> dict:
        """
        Initiate forgot password flow.

        Args:
            email: User email.

        Returns:
            Response with delivery details.
        """
        try:
            response = self._cognito.forgot_password(
                ClientId=self.client_id,
                Username=email,
            )
            logger.info(f"Password reset initiated for: {email}")
            return response

        except ClientError as e:
            logger.error(f"Forgot password failed: {e}")
            raise AuthError(str(e)) from e

    def confirm_forgot_password(self, email: str, confirmation_code: str, new_password: str) -> dict:
        """
        Confirm forgot password with new password.

        Args:
            email: User email.
            confirmation_code: Verification code.
            new_password: New password.

        Returns:
            Confirmation response.
        """
        try:
            response = self._cognito.confirm_forgot_password(
                ClientId=self.client_id,
                Username=email,
                ConfirmationCode=confirmation_code,
                Password=new_password,
            )
            logger.info(f"Password reset confirmed for: {email}")
            return response

        except ClientError as e:
            logger.error(f"Confirm forgot password failed: {e}")
            raise AuthError(str(e)) from e

    def change_password(self, old_password: str, new_password: str) -> dict:
        """
        Change password for authenticated user.

        Args:
            old_password: Current password.
            new_password: New password.

        Returns:
            Change password response.
        """
        if not self._access_token:
            raise AuthError("Not authenticated")

        try:
            response = self._cognito.change_password(
                PreviousPassword=old_password,
                ProposedPassword=new_password,
                AccessToken=self._access_token,
            )
            logger.info("Password changed")
            return response

        except ClientError as e:
            logger.error(f"Change password failed: {e}")
            raise AuthError(str(e)) from e

    def delete_account(self):
        """Delete the current user's account."""
        if not self._access_token:
            raise AuthError("Not authenticated")

        try:
            self._cognito.delete_user(AccessToken=self._access_token)
            logger.info("Account deleted")
            self.sign_out()

        except ClientError as e:
            logger.error(f"Delete account failed: {e}")
            raise AuthError(str(e)) from e


class AuthError(Exception):
    """Authentication error."""

    pass
