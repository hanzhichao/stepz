import re
import os
import unittest
import types
from collections import ChainMap
import requests
from operator import eq, gt, lt, ge, le
from logz import log
from parserz import parser


STEP_KEYS = {'key', 'name', 'skip', 'target', 'args', 'kwargs', 'validate', 'extract', 'times', 'concurrency'}
COMPARE_FUNCS = dict(
    eq=eq, gt=gt, lt=lt, ge=ge, le=le,
    len_eq=lambda x, y: len(x) == len(y),
    str_eq=lambda x, y: str(x) == str(y),
    type_match=lambda x, y: isinstance(x, y),
    regex_match=lambda x, y: re.match(y, x)
)


FUNCTIONS = dict(
    log=log.info,
    get=requests.get,
    request=requests.request,
)


def split_and_strip(text, seq):
    return [item.strip() for item in text.split(seq)]


class Context(object):
    def __init__(self):
        self._variables = ChainMap({}, os.environ)
        self._functions = FUNCTIONS
        self._config = {}

    def __getitem__(self, key):
        return self.get(key)

    def get(self, key):
        return self._variables.get(key)

    def update(self, data: dict):
        if isinstance(data, dict):
            self._variables.update(data)

    def register_function(self, func_name, func):
        self._functions[func_name] = func

    def get_function(self, func_name):
        return self._functions.get(func_name)

    def update_functions(self, functions: dict):
        assert isinstance(functions, dict), 'functions应为字典类型'
        self._functions.update(functions)

    def parse(self, data):
        return parser.parse(data, self._variables)

    def update_config(self, config: dict):
        assert isinstance(config, dict), 'config应为字典类型'
        self._config.update(config)

    def __str__(self):
        return f'varialbes: {self._variables} config: {self._config} functions: {self._functions}'


class Step(object):
    def __init__(self, data: (str, dict)):
        self.raw = data
        self.data = data = self.format_data(data)

        self.key = data.get('key')
        self.name = data.get('name')
        self.skip = data.get('skip')

        self.target = data.get('target')
        self.args = data.get('args')
        self.kwargs = data.get('kwargs')
        if not self.target:
            self.target, self.args, self.kwargs = self.guess_target_args_kwargs(data)

        self.extract = data.get('extract')
        self.validate = data.get('validate')
        self.times = data.get('times')
        self.concurrency = data.get('concurrency')
        self.timeout = data.get('timeout')

        self.result = None
        self.status = None

    def format_data(self, data: dict):
        """
        data: name: 步骤2
              request:
                url: https://httpbin.org/post
                method: post
                data: {url: $url}
        :return:
            data: target: request
                  args: [],
                  kwargs:
                    url: ...
        """
        assert isinstance(data, (str, dict))
        if isinstance(data, str):
            target, *args = data.split()
            key = None
            if '=' in target:
                key, target = split_and_strip(target, '=')
            kwargs = {item.split('=', 1)[0]: item.split('=', 1)[1] for item in args if '=' in item}
            args = [item for item in args if '=' not in item]
            data = dict(key=key, target=target, args=args, kwargs=kwargs)
        elif not data.get('target'):
            data['target'], data['args'], data['kwargs'] = self.guess_target_args_kwargs(data)
        return data

    def guess_target_args_kwargs(self, data: dict):
        keys = data.keys() - STEP_KEYS
        if keys:
            target = keys.pop()
            attrs = data.get(target)
            assert isinstance(attrs, (str, list, dict)), f'{target} 参数: {attrs} 必须为list或dict'
            if isinstance(attrs, str):
                attrs = [attrs]
            args, kwargs = (attrs, {}) if isinstance(attrs, list) else ([], attrs)
            return target, args, kwargs
        return None, None, None


    def do_extract(self, context: Context):
        """处理提取变量"""
        assert isinstance(self.extract, dict), 'self.extract应为字典类型'
        for key, value in self.extract.items():
            context.update(dict(key= parser.parse(value, context._variables)))

    def do_validate(self, context: Context):
        """处理断言"""
        assert isinstance(self.validate, list), 'self.validate应为列表类型'
        for line in self.validate:
            if 'comparator' in line:
                comparator = line.get('comparator')
                check = line.get('check')
                expect = line.get('expect')
            else:
                comparator, value = tuple(line.items())[0]
                check, expect = value
            compare_func = COMPARE_FUNCS.get(comparator)
            field = parser.parse(check, context._variables)

            assert compare_func(field, expect), f'表达式: {check} 实际结果: {field} {type(field)} not {comparator} 期望结果: {expect} {type(expect)}'

    def do_function(self, context: Context):
        func = context.get_function(self.target)
        assert func is not None, f'{context} 中未找到函数: {self.target}'
        args = parser.parse(self.args, context) if self.args else []
        kwargs = parser.parse(self.kwargs, context) if self.kwargs else {}
        result = func(*args, **kwargs)
        context.update(dict(result=result))
        if self.key:
            context.update(dict(key=result))
        return result

    def run(self, context: Context):
        self.result = self.do_function(context)
        if self.extract:
            self.do_extract(context)
        if self.validate:
            self.do_validate(context)


class TestSuiteBuilder(object):
    """一个文件是一个TestSuite"""
    def __init__(self, data: dict):
        assert isinstance(data, dict), 'data应为字典类型'
        self.data = data
        self.name = data.get('name')
        self.variables = data.get('variables')
        self.config = data.get('config')
        self.keywords = data.get('keywords')
        self.tests = data.get('tests')
        self._context = self.build_context()

    def build_context(self):
        context = Context()
        context.update_functions(FUNCTIONS)
        if self.variables:
            context.update(self.variables)
        if self.config:
            context.update_config(self.config)
        if self.keywords:
            functions = self.build_keywords()
            context.update_functions(functions)

        return context

    def build_keywords(self):
        if self.keywords:
            functions = {}
            [functions.update(Keyword(key, data).build_function()) for key, data in self.keywords.items()]
            return functions

    def build_case(self, index, data) -> types.FunctionType:
        assert isinstance(data, dict), 'data必须为dict格式'
        def test_method(self):
            if data.get('skip'):
                raise unittest.SkipTest('Skip=True跳过用例')
            if data.get('variables'):
                self.context.update(data.get('variables'))
            steps = data.get('steps', [])
            for step in steps:
                Step(step).run(self.context)

        test_method.__name__ = f'test_{index + 1}'
        test_method.__doc__ = data.get('name')
        test_method.name = data.get('key') or 'test_method'
        test_method.tags = data.get('tags')
        test_method.timeout = data.get('timeout')
        return test_method

    def build_suite(self):
        class TestStep(unittest.TestCase):
            @classmethod
            def setUpClass(cls) -> None:
                cls.context = self._context
        if not self.tests:   # todo tests结构验证
            log.warning('未发现tests')
            return unittest.TestSuite()
        [setattr(TestStep, f'test_{index + 1}', self.build_case(index, test)) for index, test in enumerate(self.tests)]

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestStep)
        return suite

    def run(self):
        suite = self.build_suite()
        runner = unittest.TextTestRunner(verbosity=2)
        return runner.run(suite)


class Keyword(object):
    """关键字, StepGroup, 可以包含多个步骤, 生成函数"""
    def __init__(self, key, data: dict):
        """
        :param key:  open
        :param data: name: 打开
                     args: [a,b]
                     skip: True
                     steps:
                       - log $a
                       - log $b
                     :return:
                       b: $b
        """
        self.data = data
        self.key = key
        self.name = data.get('name')
        self.skip = data.get('skip')
        self.args = data.get('args')
        self.steps = data.get('steps', [])
        self._return = data.get('return')
        self.extract = data.get('extract')
        self.validate = data.get('validate')

    def build_function(self):
        def func(*real_args):
            kwargs = dict(zip(self.args, real_args))
            locals().update(kwargs)
            for step in self.steps:
                step.run(locals(), step)
            return locals().get(self._return)

        func.__name__ = self.key
        func.__doc__ = self.name
        return {self.key: func}



