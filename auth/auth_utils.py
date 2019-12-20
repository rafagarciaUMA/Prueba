from flask import request
import hashlib
from jwcrypto import jwt
from functools import wraps
import ast
from DB_Model import User, Registry, Rol, db
from flask import session, jsonify
from datetime import datetime
from settings import Settings

key = Settings().KEY


def preValidation(request, functional_part):
    username = request.authorization.username
    password = hashlib.md5(request.authorization.password.encode()).hexdigest()

    data = User.query.filter_by(username=username, password=password).first()
    if data is not None and data.active:
        now = datetime.now()
        Etoken = jwt.JWT(header={'alg': 'A256KW', 'enc': 'A256CBC-HS512'},
                         claims={'username': username, 'password': password, 'timeout': datetime.timestamp(now) + 120})

        Etoken.make_encrypted_token(key)
        token = Etoken.serialize()
        return functional_part(token)

    elif data is None:
        return jsonify(result='No user registered/active with that user/password'), 400

    else:
        return jsonify(result='User ' + username + ' is not activated'), 400


def auth(f):
    @wraps(f)
    def auth_validator(*args, **kwargs):
        auth = token_auth_validator(request)
        if not auth[0]:
            return auth[-1]
        return f(*args, **kwargs)

    return auth_validator


def admin_auth(f):
    @wraps(f)
    def auth_validator(*args, **kwargs):
        username = request.authorization.username
        password = request.authorization.password
        data_user = User.query.filter_by(username=username, password=hashlib.md5(password.encode()).hexdigest()).first()
        data_rol = Rol.query.filter_by(username=username, rol_name='Admin').first()
        if not (data_user and data_rol):
            return jsonify(result='Invalid Permission'), 401
        return f(*args, **kwargs)

    return auth_validator


def token_auth_validator(request=None):
    result = (True, None)
    if session.get('token') or session.get('token') is False:
        token = session.get('token')
        token_valid = validate_token(token, request)

        # Validate token, None in this function means no problem detected
    if token_valid is not None:
        result = (False, (jsonify(result=token_valid), 400))

    return result


def validate_token(token, request):
    try:
        if not token:
            return 'Login or set a Token access is required'

        metadata = ast.literal_eval(jwt.JWT(key=key, jwt=token).claims)

        now = datetime.now()
        if metadata.get('timeout') >= datetime.timestamp(now):
            data = User.query.filter_by(username=metadata.get('username'), password=metadata.get('password')).first()
        else:
            return 'Token expired'
        if data is not None:
            if request.data:
                new_action = Registry(username=metadata.get('username'),
                                      action=str(request.method + ' ' + request.path),
                                      data=str(request.get_json()))
            else:
                new_action = Registry(username=metadata.get('username'),
                                      action=str(request.method + ' ' + request.path))
            db.session.add(new_action)
            db.session.commit()
            pass
        else:
            raise Exception()
    except:
        return 'No valid Token given'
