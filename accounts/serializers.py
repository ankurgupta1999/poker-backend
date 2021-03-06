from datetime import timedelta
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from smtplib import SMTPException

from accounts import (constants as accounts_constants,
                      models as accounts_models, tasks as accounts_tasks)
from commons import (models as common_models, utils)
from pokerboards import (models as pokerboard_models)


class EmailVerifySerializer(serializers.Serializer):
    """This serializer is used to send email to verify users for signup."""

    email = serializers.EmailField()
    name = serializers.CharField()
    purpose = serializers.IntegerField()

    def validate_email(self, email):
        email = email.lower()
        if accounts_models.User.objects.filter(email__exact=email).exists():
            raise serializers.ValidationError(
                accounts_constants.USER_ALREADY_EXIST)
        return email

    def create(self, validated_data):
        email = validated_data.get('email').lower()
        name = validated_data.get('name')
        purpose = validated_data.get('purpose')
        token_key = utils.token_generator()

        save_point = transaction.savepoint()
        common_models.EmailVerification.objects.create(
            email=email, name=name, token_key=token_key, purpose=purpose)
        absurl = f"{accounts_constants.BASE_URL}/signup?token={token_key}"
        subject = accounts_constants.EMAIL_VERIFICATION_SUBJECT
        message = "{} {} {} {} {}" .format(
            accounts_constants.GREETING, name, accounts_constants.SIGNUP_MESSAGE, absurl, accounts_constants.LINK_NOT_WORK)
        try:
            accounts_tasks.send_verification_mail.delay(
                subject, email, message)

        except SMTPException as e:
            """It will catch other errors related to SMTP."""

            transaction.savepoint_rollback(save_point)
            return {"message": f'There was an error sending an email.'}

        except Exception as e:
            """It will catch All other possible errors."""

            transaction.savepoint_rollback(save_point)
            return {"message": f'Mail Sending Failed!'}

        return {"message": accounts_constants.TOKEN_SENT}


class SendInvitationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    purpose = serializers.IntegerField()
    id = serializers.IntegerField()

    def create(self, validated_data):
        email = validated_data.get('email').lower()
        purpose = validated_data.get('purpose')
        id = validated_data.get('id')
        token_key = utils.token_generator()

        save_point = transaction.savepoint()
        verification_obj = common_models.EmailVerification.objects.create(
            email=email, token_key=token_key, purpose=purpose)
        absurl = f"{accounts_constants.BASE_URL}/signup?token={token_key}"

        if purpose == accounts_constants.GROUP_INVITATION_PURPOSE:
            subject = accounts_constants.GROUP_INVITATION_SUBJECT
            message = "{} {} {} {}" .format(
                accounts_constants.GREETING, accounts_constants.GROUP_INVITATION_MESSAGE, absurl, accounts_constants.LINK_NOT_WORK)
            if accounts_models.User.objects.filter(email=email).exists():
                """if user exist in the app and he is already invited in the same group and invitation is still pending, then user cannot be reinvite"""

                user = accounts_models.User.objects.get(email=email)
                queryset = accounts_models.GroupInvitation.objects.filter(user=user, group_id=id,status=accounts_constants.INVITATION_STATUS_PENDING)
                if len(queryset) > 0:
                    raise serializers.ValidationError({accounts_constants.ALREADY_INVITED})
                accounts_models.GroupInvitation.objects.create(
                    group_id=id, user_id=user.id, verification_id=verification_obj.id)
            else:
                accounts_models.GroupInvitation.objects.create(
                    group_id=id, verification_id=verification_obj.id)
        else:
            """for pokerboard Invitation."""
            role = self.context['request'].query_params.get('role')
            subject = accounts_constants.POKERBOARD_INVITATION_SUBJECT
            message = accounts_constants.POKERBOARD_INVITATION_MESSAGE.format(
                accounts_constants.USER_ROLE[role], absurl)
            if accounts_models.User.objects.filter(email=email).exists():
                """if user exist in the app and he is already invited in the same group for the same role and invitation is still pending, then user cannot be reinvite"""
                
                user = accounts_models.User.objects.get(email=email)
                queryset = pokerboard_models.PokerboardInvitation.objects.filter(
                    user=user, pokerboard_id=id, status=accounts_constants.INVITATION_STATUS_PENDING,role=[role])
                print(queryset)
                if len(queryset) > 0:
                    raise serializers.ValidationError({accounts_constants.ALREADY_INVITED})
                pokerboard_models.PokerboardInvitation.objects.create(
                    pokerboard_id=id, user_id=user.id, verification_id=verification_obj.id, role=[role])
            else:
                pokerboard_models.PokerboardInvitation.objects.create(
                    pokerboard_id=id, verification_id=verification_obj.id, role=[role])
        try:
            accounts_tasks.send_verification_mail.delay(
                subject, email, message)

        except SMTPException as e:
            """It will catch other errors related to SMTP."""

            transaction.savepoint_rollback(save_point)
            return {"message": f'There was an error sending an email.'}

        except Exception as e:
            """It will catch All other possible errors."""

            transaction.savepoint_rollback(save_point)
            return {"message": f'Invitation Failed!'}

        return {"message": accounts_constants.INVITED}


class VerifyTokenSerializer(serializers.Serializer):
    token = serializers.CharField()

    def validate(self, data):
        token = data['token']
        if not common_models.EmailVerification.objects.filter(token_key=token).exists():
            raise serializers.ValidationError(
                {'message': accounts_constants.INVALID_TOKEN, 'status': status.HTTP_400_BAD_REQUEST})
        email_verification_obj = common_models.EmailVerification.objects.get(
            token_key=token)

        if email_verification_obj.is_used or timezone.now() > email_verification_obj.created_at+timedelta(minutes=accounts_constants.EXPIRY_TIME):
            raise serializers.ValidationError(
                {'message': accounts_constants.TOKEN_EXPIRED_OR_ALREADY_USED, 'status': status.HTTP_400_BAD_REQUEST})

        return data

    def create(self, validated_data):
        token = validated_data.get('token')
        email_verification_obj = common_models.EmailVerification.objects.get(
            token_key=token)

        if email_verification_obj.purpose == accounts_constants.SIGNUP_PURPOSE:
            """Check whether user already exist with the same email, it could be possible that user registered himself with another verification link and trying to register again with different link."""

            if accounts_models.User.objects.filter(email=email_verification_obj.email).exists():
                return {'message': accounts_constants.USER_ALREADY_EXIST, 'status': status.HTTP_204_NO_CONTENT}
            return {'message': accounts_constants.SUCCESSFULLY_VERIFY_ACCOUNT, 'email': {email_verification_obj.email}, 'name': {email_verification_obj.name}, 'status': status.HTTP_200_OK}

        elif email_verification_obj.purpose == accounts_constants.GROUP_INVITATION_PURPOSE:

            group_invitation_obj = accounts_models.GroupInvitation.objects.get(
                verification=email_verification_obj.id)
            if group_invitation_obj.status == accounts_constants.INVITATION_STATUS_CANCELLED:
                raise serializers.ValidationError(
                    detail={'message': accounts_constants.INVITATION_CANCELLED, 'status': status.HTTP_400_BAD_REQUEST})

            if group_invitation_obj.status == accounts_constants.INVITATION_STATUS_DECLINED:
                raise serializers.ValidationError(
                    detail={'message': accounts_constants.INVITATION_DECLINED, 'status': status.HTTP_400_BAD_REQUEST})

            if accounts_models.User.objects.filter(email=email_verification_obj.email).exists():
                """If user already exist then add him to the group and mark invitation status in GroupInvitation table as "accepted" and mark "is_used" in EmailVerification table true. and display message in frontend (added to the group, pls login)."""

                user = accounts_models.User.objects.get(
                    email=email_verification_obj.email)
                group_obj = accounts_models.Group.objects.get(
                    title=group_invitation_obj.group)
                group_obj.users.add(user)
                group_obj.save()
                group_invitation_obj.status = accounts_constants.INVITATION_STATUS_ACCEPTED
                group_invitation_obj.save()
                email_verification_obj.is_used = True
                email_verification_obj.save()
                return {'message': accounts_constants.USER_ADDED, 'status': status.HTTP_204_NO_CONTENT}
            else:
                """ redirect to signup page and allow user to register in the app without any further verification. and user will automatically added to the group after successful signup."""

                return {'message': accounts_constants.ADD_AFTER_SIGNUP, 'email': {email_verification_obj.email}, 'name': {email_verification_obj.name}, 'status': status.HTTP_200_OK}
        else:
            """if invitation purpose is 2(pokerboard invite)"""
            pokerboard_invitation_obj = pokerboard_models.PokerboardInvitation.objects.get(verification=email_verification_obj.id)
            if pokerboard_invitation_obj.status == accounts_constants.INVITATION_STATUS_CANCELLED:
                raise serializers.ValidationError(
                    detail={'message': accounts_constants.INVITATION_CANCELLED, 'status': status.HTTP_400_BAD_REQUEST})

            if pokerboard_invitation_obj.status == accounts_constants.INVITATION_STATUS_DECLINED:
                raise serializers.ValidationError(
                    detail={'message': accounts_constants.INVITATION_DECLINED, 'status': status.HTTP_400_BAD_REQUEST})
                
            if accounts_models.User.objects.filter(email=email_verification_obj.email).exists():
                user = accounts_models.User.objects.get(
                    email=email_verification_obj.email)
                pokerboard_models.UserPokerboard.objects.create(user_id=user.id, pokerboard_id=pokerboard_invitation_obj.pokerboard.id, role=pokerboard_invitation_obj.role)
                pokerboard_invitation_obj.status = accounts_constants.INVITATION_STATUS_ACCEPTED
                pokerboard_invitation_obj.save()
                email_verification_obj.is_used = True
                email_verification_obj.save()
                return {'message': accounts_constants.USER_ADDED, 'status': status.HTTP_204_NO_CONTENT}
            else:
                return {'message': accounts_constants.ADD_AFTER_SIGNUP, 'email': {email_verification_obj.email}, 'name': {email_verification_obj.name}, 'status': status.HTTP_200_OK}


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(max_length=128)

    def validate(self, data):
        data['email'] = data['email'].lower()
        username = data.get('email')
        password = data.get('password')

        user = authenticate(username=username, password=password)
        if not user:
            raise serializers.ValidationError(
                accounts_constants.INVALID_CREDENTIALS, code='authorization')
        else:
            return data


class UserReadSerializer(serializers.ModelSerializer):

    class Meta:
        model = accounts_models.User
        fields = ['id', 'email', 'first_name', 'last_name']


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = accounts_models.User
        fields = ['id', 'email', 'first_name', 'last_name', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def validated_email(self, email):
        email = email.lower()
        if self.instance is not None and self.instance.email != email:
            raise serializers.ValidationError(
                accounts_constants.EMAIL_CANNOT_UPDATE)
        return email

    def create(self, validated_data):
        user = super().create(validated_data)
        user.set_password(validated_data['password'])
        user.save()
        """once user created successfully,access invitation token from requested data and check if the user is registering through group/pokerboard invitation, if yes then update the group invitation status and directly adding user in the group."""

        token = self.context['request'].data['token']
        if not common_models.EmailVerification.objects.filter(token_key=token).exists():
            return user

        email_verification_obj = common_models.EmailVerification.objects.get(
            token_key=token)
        """If user is coming through Group Invitation."""
        
        if accounts_models.GroupInvitation.objects.filter(verification=email_verification_obj).exists():
            group_invitation_obj = accounts_models.GroupInvitation.objects.get(
                verification=email_verification_obj)
            group_obj = accounts_models.Group.objects.get(
                title=group_invitation_obj.group)
            group_obj.users.add(user)
            group_obj.save()
            group_invitation_obj.status = accounts_constants.INVITATION_STATUS_ACCEPTED
            group_invitation_obj.save()
            """If user is coming through Pokerboard Invitation"""
            
        elif pokerboard_models.PokerboardInvitation.objects.filter(verification=email_verification_obj).exists():
            pokerboard_invitation_obj = pokerboard_models.PokerboardInvitation.objects.get(
                verification=email_verification_obj)
            pokerboard_models.UserPokerboard.objects.create(user_id=user,pokerboard_id=pokerboard_invitation_obj.pokerboard.id,role=pokerboard_invitation_obj.role)
            pokerboard_invitation_obj.status = accounts_constants.INVITATION_STATUS_ACCEPTED
            pokerboard_invitation_obj.save()
        email_verification_obj.is_used = True
        email_verification_obj.save()
        return user

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            if attr == 'password':
                instance.set_password(value)
            else:
                setattr(instance, attr, value)
        instance.save()
        return instance


class GroupViewSerializer(serializers.ModelSerializer):
    users = UserSerializer(many=True, read_only=True)
    admin = UserReadSerializer(read_only=True)

    class Meta:
        model = accounts_models.Group
        fields = ['id', 'admin', 'title', 'description', 'users']


class GroupSerializer(serializers.ModelSerializer):

    class Meta:
        model = accounts_models.Group
        fields = ['id', 'admin', 'title', 'description', 'users']

    def validated_admin(self, admin):
        """applying validator so that admin cannot be updated"""

        if self.instance is not None and self.instance.admin != admin:
            raise serializers.ValidationError(
                accounts_constants.ADMIN_CANNOT_UPDATE)
        return admin

    def create(self, validated_data):
        """override create method to add admin in the group by default when the group created."""

        admin = self.context["request"].user
        validated_data["admin"] = admin
        if admin not in validated_data["users"]:
            validated_data["users"].append(admin)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "users" in validated_data:
            instance.users.add(*validated_data["users"])
        if "title" in validated_data:
            instance.title = validated_data["title"]
        if "description" in validated_data:
            instance.description = validated_data["description"]
        instance.save()
        return instance


class UserJiraTokenSerializer(serializers.ModelSerializer):

    class Meta:
        model = accounts_models.UserJiraToken
        fields = ['user', 'jira_token', 'expiry']


class UserGroupSerializer(GroupSerializer):
    users = UserSerializer(many=True, read_only=True)
    admin = UserSerializer(read_only=True)


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)


class VerificationSerializer(serializers.ModelSerializer):

    class Meta:
        model = common_models.EmailVerification
        fields = ['id', 'email']


class GroupInvitesSerializer(serializers.ModelSerializer):
    """This serializer is to get the list of all group invitations group admin send."""

    group = GroupViewSerializer()
    verification = VerificationSerializer()

    class Meta:
        model = accounts_models.GroupInvitation
        fields = ['id', 'group', 'status', 'verification']


class UserGroupInvitesSerializer(serializers.ModelSerializer):
    """This serializer is to get the list of all group invitations user received."""

    group = GroupViewSerializer()

    class Meta:
        model = accounts_models.GroupInvitation
        fields = ['id', 'group', 'status']


class UserGroupInvitesUpdateSerializer(serializers.Serializer):
    """Thi serializer is to update invitation(accept/decline group invitation).If user will accept the invitation he will be added to the group."""

    status = serializers.IntegerField()

    def update(self, instance, validated_data):
        if validated_data['status'] == accounts_constants.INVITATION_STATUS_DECLINED:
            instance.status = accounts_constants.INVITATION_STATUS_DECLINED
            instance.save()
            return instance

        group_obj = accounts_models.Group.objects.get(title=instance.group)
        if instance.user is not None:
            group_obj.users.add(instance.user)
            group_obj.save()
            instance.status = accounts_constants.INVITATION_STATUS_ACCEPTED
            instance.save()
        return instance
