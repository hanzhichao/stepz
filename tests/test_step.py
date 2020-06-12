from stepz import Step, TestSuiteBuilder, Context
import yaml
import os
import requests


def test_get_target_no_target():
    data = '''name: 步骤1
target: request
skip: True
times: 3
request:
  url: /get
  method: get
  params: {a: $a, username: $username, password: $password, user: $SMTP_USER}
validate:
  - response.status_code == 200
  - eq: [status_code, 200]
extract:
  url: response_json['url']'''
    data = yaml.safe_load(data)
    assert Step(data).target == 'request'


def test_get_target_text():
    data = 'sh ls'
    assert Step(data).target == 'sh'
    data = dict(sh='ls')
    assert Step(data).target == 'sh'


def test_step_run():
    variables = {
        'a': 1, 'b': 2,
        'functions': {'log': print, 'get': requests.get, 'request': requests.request}
    }

    data = 'log hello,world'
    context = Context()
    context.update(variables)
    Step(data).run(context)
    data = {'get': 'https://www.baidu.com/'}
    s = Step(data)
    s.run(context)
    assert s.result.status_code == 200
    data = {
        'request':
            {'url': 'https://httpbin.org/get', 'method': 'get', 'params': {'a': 123}},
        'extract': {'url': '$result.json.url'},
        'validate': [{'eq': ['$result.status_code', 200]}]
    }
    s = Step(data)
    s.run(context)


def test_suite_run():
    data_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tests','data.yaml')
    with open(data_file, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    result = TestSuiteBuilder(data).run()
    print(result)


def test_guess_target_args_kwargs():
    data = '''name: 步骤1
request:
  url: https://httpbin.org/get
  method: get
  params: {a: $a, username: $username, password: $password, user: $SMTP_USER}
validate:
  - eq: [$result.status_code, 200]
extract:
  url: $result.json.url'''
    data = yaml.safe_load(data)
    s = Step(data)
    result = s.guess_target_args_kwargs(data)
    print(result)

