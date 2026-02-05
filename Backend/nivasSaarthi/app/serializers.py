from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import NewUser

class UserBaseRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

class UserRegistrationSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=30)
    last_name = serializers.CharField(max_length=30)
    role = serializers.ChoiceField(choices=NewUser.USER_ROLES)
    preferred_language = serializers.ChoiceField(choices=NewUser.INDIAN_LANGUAGES)
    phone_number = serializers.CharField(max_length=10)
    address = serializers.CharField(max_length=255, required=False)
    city = serializers.CharField(max_length=100, required=False)
    state = serializers.CharField(max_length=100, required=False)
    pincode = serializers.CharField(max_length=10, required=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False)