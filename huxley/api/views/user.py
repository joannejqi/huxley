# Copyright (c) 2011-2014 Berkeley Model United Nations. All rights reserved.
# Use of this source code is governed by a BSD License (see LICENSE).

from django.contrib.auth import login, logout
from django.http import Http404

from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import (APIException, AuthenticationFailed,
                                       PermissionDenied)
from rest_framework.response import Response

from huxley.accounts.models import User
from huxley.accounts.exceptions import AuthenticationError, PasswordChangeFailed
from huxley.api.permissions import IsPostOrSuperuserOnly, IsUserOrSuperuser
from huxley.api.serializers import CreateUserSerializer, UserSerializer
from huxley.core.models import School


class UserList(generics.ListCreateAPIView):
    authentication_classes = (SessionAuthentication,)
    queryset = User.objects.all()
    permission_classes = (IsPostOrSuperuserOnly,)

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CreateUserSerializer
        return UserSerializer

    def create(self, request, *args, **kwargs):
        '''Intercept the create request and extract the country preference data,
        create the user+school as normal, then create the country preferences.

        This is a workaround for Django Rest Framework not supporting M2M
        fields with a "through" model.'''
        data = request.DATA
        country_ids = data.get('school', {}).pop('country_preferences', [])

        response = super(UserList, self).create(request, *args, **kwargs)
        school_data = response.data.get('school', {}) or {}

        school_id = None
        if isinstance(school_data, dict):
            school_id = school_data.get('id')

        if school_id:
            prefs = School.update_country_preferences(school_id, country_ids)
            response.data['country_preferences'] = prefs

        return response


class UserDetail(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = (SessionAuthentication,)
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = (IsUserOrSuperuser,)


class CurrentUser(generics.GenericAPIView):
    authentication_classes = (SessionAuthentication,)

    def get(self, request, *args, **kwargs):
        '''Get the current user if they're authenticated.'''
        if not request.user.is_authenticated():
            raise Http404
        return Response(UserSerializer(request.user).data)

    def post(self, request, *args, **kwargs):
        '''Log in a new user.'''
        if request.user.is_authenticated():
            raise PermissionDenied('Another user is currently logged in.')

        try:
            data = request.DATA
            user = User.authenticate(data['username'], data['password'])
        except AuthenticationError as e:
            raise AuthenticationFailed(str(e))

        login(request, user)
        return Response(UserSerializer(user).data,
                        status=status.HTTP_201_CREATED)

    def delete(self, request, *args, **kwargs):
        '''Log out the currently logged-in user.'''
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserPassword(generics.GenericAPIView):
    authentication_classes = (SessionAuthentication,)

    def post(self, request, *args, **kwargs):
        '''Reset a user's password and email it to them.'''
        try:
            User.reset_password(request.DATA.get('username'))
            return Response(status=status.HTTP_201_CREATED)
        except User.DoesNotExist:
            raise Http404

    def put(self, request, *args, **kwargs):
        '''Change the authenticated user's password.'''
        if not request.user.is_authenticated():
            raise PermissionDenied()

        data = request.DATA
        password, new_password = data.get('password'), data.get('new_password')

        try:
            request.user.change_password(password, new_password)
            return Response(status=status.HTTP_200_OK)
        except PasswordChangeFailed as e:
            raise APIException(str(e))
