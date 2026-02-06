from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import NewUser

class UserBaseRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)

class UserRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewUser
        fields = ['first_name', 'last_name', 'role', 'preferred_language', 'phone_number',
                  'address', 'city', 'state', 'pincode', 'location']
