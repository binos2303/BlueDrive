"""Kiểm tra test harness không dùng cấu hình/secret hoặc cổng dịch vụ kế thừa."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from securedrive.test_environment import approved_database, validate_target, TARGET_MARKER
from django.core.exceptions import ImproperlyConfigured


BACKEND = Path(__file__).resolve().parents[1]


class IsolatedSettingsTests(unittest.TestCase):
    def settings_snapshot(self, additions=None):
        environment = {key: value for key, value in os.environ.items() if not key.startswith('BLUEDRIVE_TEST_DB_')}
        environment.update(additions or {})
        code = """
import json, os
from unittest.mock import patch
runtime_secret = os.environ.get('SECRET_KEY')
runtime_db_password = os.environ.get('DB_PASSWORD')
test_db_password = os.environ.get('BLUEDRIVE_TEST_DB_PASSWORD', '')
# Nếu dotenv cố mở file private thì subprocess phải thất bại.
with patch('dotenv.main.DotEnv', side_effect=AssertionError('dotenv must stay disabled')):
    from securedrive import test_settings as settings
print(json.dumps({
    'db': {key: settings.DATABASES['default'][key] for key in ('NAME','HOST','PORT','USER')},
    'flags': {name: getattr(settings, name) for name in dir(settings) if name.endswith('_ENABLED') and name.startswith('SECUREDRIVE_')},
    'private_key_inherited': settings.SECRET_KEY == runtime_secret,
    'private_password_inherited': settings.DATABASES['default']['PASSWORD'] == runtime_db_password,
    'test_password_matches_contract': settings.DATABASES['default']['PASSWORD'] == test_db_password,
    'endpoint': settings.SECUREDRIVE_STORAGE_ENDPOINT_URL,
    'profiles': settings.SECUREDRIVE_STORAGE_CONNECTION_PROFILES,
    'middleware': settings.MIDDLEWARE,
    'media_is_private': str(settings.MEDIA_ROOT) != str(settings.BASE_DIR / 'media'),
    'live_gate': os.environ.get('SEAWEEDFS_INTEGRATION'),
    'validators': settings.AUTH_PASSWORD_VALIDATORS,
    'email': settings.EMAIL_BACKEND,
    'aes_key_matches_test_settings': os.environ.get('SECUREDRIVE_AES_KEY') == settings.SECUREDRIVE_AES_KEY,
    'runtime_aliases_absent': not any(key in os.environ for key in ('RUNTIME_ACCESS_V1','RUNTIME_SECRET_V1','RUNTIME_MONITOR_TOKEN','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','PGHOSTADDR','PGSERVICE','PGOPTIONS','HTTPS_PROXY')),
    'dotenv_disabled_after_import': os.environ.get('PYTHON_DOTENV_DISABLED') == '1',
    'aws_files_disabled': os.environ.get('AWS_SHARED_CREDENTIALS_FILE') == os.devnull and os.environ.get('AWS_CONFIG_FILE') == os.devnull,
    'db_options': settings.DATABASES['default']['OPTIONS'],
}))
"""
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-c", code], cwd=BACKEND,
            env=environment, capture_output=True, text=True, encoding="utf-8",
        )

    def test_inherited_runtime_config_and_dotenv_cannot_change_test_contract(self):
        inherited = {
            "SECRET_KEY": "inherited-sentinel",
            "DB_NAME": "serving-database",
            "DB_PASSWORD": "inherited-sentinel",
            "SECUREDRIVE_STORAGE_ENDPOINT_URL": "http://runtime.example.invalid",
            "SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED": "true",
            "SECUREDRIVE_STORAGE_RUNTIME_PROBES_ENABLED": "true",
            "SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED": "true",
            "SECUREDRIVE_STORAGE_CONNECTION_PROFILES": "invalid inherited JSON",
            "SEAWEEDFS_INTEGRATION": "1",
            "BLUEDRIVE_TEST_DB_NAME": "bluedrive_test_control",
            "BLUEDRIVE_TEST_DB_HOST": "127.0.0.1",
            "BLUEDRIVE_TEST_DB_PORT": "55432",
            "BLUEDRIVE_TEST_DB_USER": "bluedrive_test",
            "BLUEDRIVE_TEST_DB_PASSWORD": "test-database-sentinel",
            **{key: 'runtime-sentinel' for key in ('RUNTIME_ACCESS_V1','RUNTIME_SECRET_V1','RUNTIME_MONITOR_TOKEN','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','PGHOSTADDR','PGSERVICE','PGOPTIONS','HTTPS_PROXY')},
        }
        result = self.settings_snapshot(inherited)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["db"], {
            "NAME": "bluedrive_test_control", "HOST": "127.0.0.1",
            "PORT": "55432", "USER": "bluedrive_test",
        })
        self.assertTrue(data["flags"])
        self.assertFalse(any(data["flags"].values()))
        self.assertFalse(data["private_key_inherited"])
        self.assertFalse(data["private_password_inherited"])
        self.assertTrue(data['test_password_matches_contract'])
        self.assertEqual(data["endpoint"], "https://storage.example.invalid")
        self.assertEqual(data["profiles"], {})
        self.assertTrue(data["media_is_private"])
        self.assertEqual(data["live_gate"], "0")
        self.assertIn("django.middleware.csrf.CsrfViewMiddleware", data["middleware"])
        self.assertIn("django.contrib.auth.middleware.AuthenticationMiddleware", data["middleware"])
        self.assertEqual(len(data["validators"]), 4)
        self.assertEqual(data["email"], "django.core.mail.backends.locmem.EmailBackend")
        self.assertTrue(data["aes_key_matches_test_settings"])
        self.assertTrue(data['runtime_aliases_absent'])
        self.assertTrue(data['dotenv_disabled_after_import'])
        self.assertTrue(data['aws_files_disabled'])
        self.assertEqual(data['db_options'], {'hostaddr':'127.0.0.1','passfile':os.devnull})

    def test_serving_database_name_is_rejected_before_connection(self):
        result = self.settings_snapshot({"BLUEDRIVE_TEST_DB_NAME": "serving-database"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("profile đã duyệt", result.stderr)

    def test_unapproved_database_coordinates_are_rejected_before_connect(self):
        for key, value in [('HOST','runtime.example.invalid'), ('HOST','localhost'), ('HOST','127.0.0.1,10.0.0.1'),
                           ('PORT','5432'), ('PORT','6432'), ('USER','postgres'), ('NAME','bluedrive_test_other'), ('TARGET','arbitrary')]:
            with self.subTest(key=key, value=value), patch('psycopg.connect') as connect:
                with self.assertRaises(ImproperlyConfigured):
                    approved_database({'BLUEDRIVE_TEST_DB_' + key: value})
                connect.assert_not_called()

    def test_ci_profile_is_explicit_and_fixed(self):
        result = self.settings_snapshot({'BLUEDRIVE_TEST_DB_TARGET':'ci', 'BLUEDRIVE_TEST_DB_PORT':'5432'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['db']['PORT'], '5432')

    def test_manage_test_cannot_bypass_guarded_database_lifecycle(self):
        environment = {key:value for key,value in os.environ.items() if not key.startswith('BLUEDRIVE_TEST_DB_')}
        result = subprocess.run([sys.executable,'-X','utf8',str(BACKEND/'manage.py'),'test','security',
                                 '--settings','securedrive.test_settings'], env=environment,
                                capture_output=True,text=True,encoding='utf-8')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('infra/seaweedfs/regression.py',result.stderr)
        self.assertNotIn('Creating test database',result.stderr)

    def test_direct_storage_and_monitoring_readers_cannot_use_inherited_credentials(self):
        code = '''
import os, django
from types import SimpleNamespace
from unittest.mock import Mock, patch
os.environ['DJANGO_SETTINGS_MODULE'] = 'securedrive.test_settings'
django.setup()
from infrastructure.connection_profiles import build_client, ProfileUnavailable
from infrastructure.prometheus import query, MonitoringError
from botocore.session import Session
assert Session().get_credentials() is None
with patch('infrastructure.connection_profiles.boto3.client') as sdk:
    try:
        build_client(SimpleNamespace(access_key_env='RUNTIME_ACCESS_V1', secret_key_env='RUNTIME_SECRET_V1'))
    except ProfileUnavailable:
        pass
    else:
        raise AssertionError('inherited storage credentials used')
    sdk.assert_not_called()
pool = Mock()
try:
    query(pool, {'token_env':'RUNTIME_MONITOR_TOKEN'}, 'up', None)
except MonitoringError:
    pass
else:
    raise AssertionError('inherited monitoring token used')
pool.urlopen.assert_not_called()
# Fixture cấp credential đúng scope vẫn được hỗ trợ và không tồn tại sau scope.
with patch.dict(os.environ, {'RUNTIME_ACCESS_V1':'fixture-access','RUNTIME_SECRET_V1':'fixture-secret'}):
    assert os.environ['RUNTIME_ACCESS_V1'] == 'fixture-access'
assert 'RUNTIME_ACCESS_V1' not in os.environ
'''
        environment = {key:value for key,value in os.environ.items() if not key.startswith('BLUEDRIVE_TEST_DB_')}
        environment.update({key:'runtime-sentinel' for key in ('RUNTIME_ACCESS_V1','RUNTIME_SECRET_V1','RUNTIME_MONITOR_TOKEN',
                           'AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_PROFILE','AWS_CONTAINER_CREDENTIALS_FULL_URI',
                           'AWS_WEB_IDENTITY_TOKEN_FILE','AWS_ROLE_ARN')})
        result = subprocess.run([sys.executable,'-X','utf8','-c',code], cwd=BACKEND, env=environment,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preloaded_runtime_settings_cannot_bypass_isolated_import(self):
        code = "import sys,types;sys.modules['securedrive.settings']=types.ModuleType('securedrive.settings');import securedrive.test_settings"
        result = subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=BACKEND,
                                capture_output=True,text=True,encoding='utf-8')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('chưa import runtime settings',result.stderr)

    def test_lifecycle_rechecks_identity_and_connection_before_create_and_drop(self):
        database = approved_database({})
        name = 'test_bluedrive_0123456789abcdef'
        connection = MagicMock()
        connection.settings_dict = {**database, 'ENGINE':'django.db.backends.postgresql',
                                    'TEST':{'NAME':name}, 'OPTIONS':{'hostaddr':'127.0.0.1','passfile':os.devnull}}
        with patch('psycopg.connect') as connect:
            execute = connect.return_value.__enter__.return_value.execute
            execute.return_value.fetchone.return_value = ('bluedrive_test_control','bluedrive_test',5432,TARGET_MARKER)
            validate_target(connection, database, name)
            connection.settings_dict['NAME'] = name
            validate_target(connection, database, name, testing=True)
            self.assertEqual(connect.call_count, 2)
            execute.return_value.fetchone.return_value = ('bluedrive_test_control','bluedrive_test',5432,None)
            with self.assertRaises(ImproperlyConfigured):
                validate_target(connection, database, name, testing=True)
            connect.reset_mock()
            for key, value in [('NAME','serving'), ('HOST','10.0.0.1'), ('PORT','6432'), ('USER','postgres'),
                               ('OPTIONS',{}), ('TEST',{'NAME':'serving'})]:
                with self.subTest(key=key), patch.dict(connection.settings_dict, {key:value}):
                    with self.assertRaises(ImproperlyConfigured):
                        validate_target(connection, database, name, testing=True)
            connect.assert_not_called()

    def test_live_provider_requires_confirmation_and_explicit_labels(self):
        runner = BACKEND.parent / 'infra' / 'seaweedfs' / 'regression.py'
        environment = {key:value for key,value in os.environ.items() if key not in {'CI','GITHUB_ACTIONS'}}
        environment['SEAWEEDFS_INTEGRATION'] = '1'
        for arguments in (['--live-storage'], ['--live-storage','security'], ['--live-storage','--confirm-live-storage','approved-fixture'],
                          ['--live-storage','--confirm-live-storage','  ','security']):
            result = subprocess.run([sys.executable,'-X','utf8',str(runner),*arguments], env=environment,
                                    capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertIn('--confirm-live-storage TEST_SCOPE',result.stderr)

    def test_live_settings_pin_test_database_before_app_initialization(self):
        code = """
import importlib.util, os
from pathlib import Path
from unittest.mock import patch
for key in list(os.environ):
    if key.startswith('BLUEDRIVE_TEST_DB_') or key in ('CI','GITHUB_ACTIONS'):
        del os.environ[key]
os.environ.update({
    'SEAWEEDFS_INTEGRATION':'1','SEAWEEDFS_ALLOW_TEST_WRITES':'1',
    'SEAWEED_S3_ENDPOINT':'http://127.0.0.1:8333','SEAWEED_S3_PUBLIC_ENDPOINT':'http://s3.localhost:8333',
    'SEAWEED_S3_BUCKET':'bluedrive-test-approved-fixture',
    'SEAWEED_S3_ACCESS_KEY':'fixture-access','SEAWEED_S3_SECRET_KEY':'fixture-secret',
    'DB_NAME':'serving','DB_HOST':'serving.invalid','DB_PORT':'6432','DB_USER':'serving',
    'EMAIL_BACKEND':'django.core.mail.backends.smtp.EmailBackend','EMAIL_HOST':'serving.invalid',
    'SECUREDRIVE_UPLOAD_SCANNER':'runtime-scanner','SECUREDRIVE_PLATFORM_SEAWEEDFS_MASTER_URL':'http://serving.invalid',
})
spec = importlib.util.spec_from_file_location('regression', Path.cwd().parent/'infra/seaweedfs/regression.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
def app_setup():
    from django.conf import settings
    database = settings.DATABASES['default']
    assert database['NAME'] == 'bluedrive_test_control'
    assert database['HOST'] == '127.0.0.1'
    assert database['PORT'] == '55432'
    assert database['USER'] == 'bluedrive_test'
    assert database['OPTIONS']['hostaddr'] == '127.0.0.1'
    assert settings.EMAIL_BACKEND == 'django.core.mail.backends.locmem.EmailBackend'
    assert Path(settings.MEDIA_ROOT).is_dir()
    assert Path(settings.MEDIA_ROOT) != settings.BASE_DIR/'media'
    assert Path(settings.MEDIA_ROOT).name.startswith('bluedrive-tests-media-')
    assert settings.SECUREDRIVE_UPLOAD_SCANNER == ''
    assert settings.SECUREDRIVE_PLATFORM_SEAWEEDFS_MASTER_URL == 'http://127.0.0.1:9'
    assert settings.SECUREDRIVE_STORAGE_ENDPOINT_URL == 'https://storage.example.invalid'
    assert settings.SECUREDRIVE_STORAGE_CONNECTION_PROFILES == {}
    assert not settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED
    assert os.environ['SEAWEED_S3_SECRET_KEY'] == 'fixture-secret'
    assert 'EMAIL_HOST' not in os.environ and 'DB_NAME' not in os.environ
    raise SystemExit(73)
with patch('django.setup',side_effect=app_setup), patch('psycopg.connect') as connect, \
     patch('dotenv.main.DotEnv',side_effect=AssertionError('private dotenv must not open')):
    try:
        runner.main(['--live-storage','--confirm-live-storage','approved-fixture','files.tests.test_seaweedfs_integration'])
    except SystemExit as result:
        assert result.code == 73
    else:
        raise AssertionError('app setup guard was bypassed')
    connect.assert_not_called()
"""
        result = subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=BACKEND,
                                capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)

    def live_runner(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('regression_guard', BACKEND.parent/'infra/seaweedfs/regression.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        return runner

    def live_fixture(self):
        return {
            'SEAWEEDFS_INTEGRATION':'1','SEAWEEDFS_ALLOW_TEST_WRITES':'1',
            'SEAWEED_S3_ENDPOINT':'http://127.0.0.1:8333',
            'SEAWEED_S3_PUBLIC_ENDPOINT':'http://s3.localhost:8333',
            'SEAWEED_S3_BUCKET':'bluedrive-test-approved-fixture',
            'SEAWEED_S3_ACCESS_KEY':'fixture-access','SEAWEED_S3_SECRET_KEY':'fixture-secret',
        }

    def assert_live_rejected_without_effects(self, labels, changes=None, scope='approved-fixture'):
        import contextlib
        import io
        runner = self.live_runner()
        with patch.dict(os.environ,{**self.live_fixture(),**(changes or {})},clear=True), \
             patch('django.setup') as setup, patch('psycopg.connect') as database, \
             patch('boto3.client') as storage, patch('tempfile.TemporaryDirectory') as media, \
             patch('pathlib.Path.write_bytes') as write_bytes, patch('pathlib.Path.write_text') as write_text, \
             patch('smtplib.SMTP') as smtp, patch.object(runner.os,'chdir') as chdir, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                runner.main(['--live-storage','--confirm-live-storage',scope,*labels])
            self.assertEqual(result.exception.code,2)
            for effect in (setup,database,storage,media,write_bytes,write_text,smtp,chdir):
                effect.assert_not_called()

    def test_live_labels_are_rejected_before_setup_connections_or_writes(self):
        approved = 'files.tests.test_seaweedfs_integration'
        for labels in (['security'], ['files'], ['infrastructure'], ['securedrive'],
                       ['files.tests.test_minio_storage_integration'], [approved+'.LoopbackHTTPTests'],
                       [approved+'.SeaweedFSIntegrationTests.test_put_get_head_range_delete_metadata_and_full_sha256'],
                       [approved,'security'], ['./backend/files/tests'], [approved+'*']):
            with self.subTest(labels=labels):
                self.assert_live_rejected_without_effects(labels)

    def test_live_module_aliases_only_discover_reviewed_provider_classes(self):
        runner = self.live_runner()
        modules = list(runner.LIVE_CLASSES)
        expected = [module+'.'+runner.LIVE_CLASSES[module] for module in modules]
        self.assertEqual(runner.approved_live_labels(modules),expected)
        self.assertEqual(runner.approved_live_labels(expected+modules),expected)

    def test_live_resource_scope_is_rejected_before_setup_or_writes(self):
        labels = ['files.tests.test_seaweedfs_integration']
        for changes in ({'SEAWEEDFS_ALLOW_TEST_WRITES':'0'}, {'SEAWEED_S3_BUCKET':'serving-bucket'},
                        {'SEAWEED_S3_BUCKET':'bluedrive-test-other'}, {'SEAWEED_S3_SECRET_KEY':''},
                        {'SEAWEED_S3_ACCESS_KEY':''}, {'SEAWEED_S3_ENDPOINT':'http://serving.invalid:8333'},
                        {'SEAWEED_S3_ENDPOINT':'http://localhost:8333'},
                        {'SEAWEED_S3_PUBLIC_ENDPOINT':'http://127.0.0.1:8333/path'},
                        {'SEAWEED_S3_PUBLIC_ENDPOINT':'http://127.0.0.1:8333?credential=fixture'},
                        {'SEAWEED_S3_PUBLIC_ENDPOINT':'http://127.0.0.1:8333#fragment'},
                        {'SEAWEED_S3_PUBLIC_ENDPOINT':'http://fixture@127.0.0.1:8333'},
                        {'SEAWEED_S3_PUBLIC_ENDPOINT':'http://:password@127.0.0.1:8333'},
                        {'SEAWEED_S3_PUBLIC_ENDPOINT':'http://127.0.0.1:\n8333'},
                        {'SEAWEED_S3_PUBLIC_ENDPOINT':'http://127.0.0.1:99999'},
                        {'FRONTEND_ORIGINS':'https://serving.invalid'}):
            with self.subTest(changes=list(changes)):
                self.assert_live_rejected_without_effects(labels,changes)
        self.assert_live_rejected_without_effects(labels,scope='../serving')

    def test_live_provider_runner_is_rejected_in_ci_before_loading_runtime(self):
        runner = BACKEND.parent / "infra" / "seaweedfs" / "regression.py"
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(runner), "--live-storage"],
            env={**os.environ, "CI": "true", "SEAWEEDFS_INTEGRATION": "1"},
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("CI mặc định", result.stderr)

    def test_unknown_runner_lifecycle_options_are_rejected(self):
        runner = BACKEND.parent / "infra" / "seaweedfs" / "regression.py"
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(runner), "--keepdb"],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 2)

    def test_production_settings_still_reject_public_http_storage(self):
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}}
        environment.update({
            "PYTHON_DOTENV_DISABLED": "1", "SECRET_KEY": "fixture-only",
            "DEBUG": "false", "SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL": "http://storage.example.invalid",
        })
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", "import securedrive.settings"],
            cwd=BACKEND, env=environment, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTPS in production", result.stderr)


if __name__ == "__main__":
    unittest.main()
