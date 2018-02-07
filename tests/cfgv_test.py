from __future__ import absolute_import
from __future__ import unicode_literals

import json

import mock
import pytest

from cfgv import apply_defaults
from cfgv import Array
from cfgv import check_and
from cfgv import check_any
from cfgv import check_array
from cfgv import check_bool
from cfgv import check_regex
from cfgv import check_type
from cfgv import Conditional
from cfgv import load_from_filename
from cfgv import Map
from cfgv import MISSING
from cfgv import Not
from cfgv import NotIn
from cfgv import Optional
from cfgv import OptionalNoDefault
from cfgv import remove_defaults
from cfgv import Required
from cfgv import RequiredRecurse
from cfgv import validate
from cfgv import ValidationError


def _assert_exception_trace(e, trace):
    inner = e
    for ctx in trace[:-1]:
        assert inner.ctx == ctx
        inner = inner.error_msg
    assert inner.error_msg == trace[-1]


def test_ValidationError_simple_str():
    assert str(ValidationError('error msg')) == (
        '\n'
        '=====> error msg'
    )


def test_ValidationError_nested():
    error = ValidationError(
        ValidationError(
            ValidationError('error msg'),
            ctx='At line 1',
        ),
        ctx='In file foo',
    )
    assert str(error) == (
        '\n'
        '==> In file foo\n'
        '==> At line 1\n'
        '=====> error msg'
    )


def test_check_regex():
    with pytest.raises(ValidationError) as excinfo:
        check_regex(str('('))
    assert excinfo.value.error_msg == "'(' is not a valid python regex"


def test_check_regex_ok():
    check_regex('^$')


def test_check_array_failed_inner_check():
    check = check_array(check_bool)
    with pytest.raises(ValidationError) as excinfo:
        check([True, False, 5])
    _assert_exception_trace(
        excinfo.value, ('At index 2', 'Expected bool got int'),
    )


def test_check_array_ok():
    check_array(check_bool)([True, False])


def test_check_and():
    check = check_and(check_type(str), check_regex)
    with pytest.raises(ValidationError) as excinfo:
        check(True)
    assert excinfo.value.error_msg == 'Expected str got bool'
    with pytest.raises(ValidationError) as excinfo:
        check(str('('))
    assert excinfo.value.error_msg == "'(' is not a valid python regex"


def test_check_and_ok():
    check = check_and(check_type(str), check_regex)
    check(str('^$'))


@pytest.mark.parametrize(
    ('val', 'expected'),
    (('bar', True), ('foo', False), (MISSING, False)),
)
def test_not(val, expected):
    compared = Not('foo')
    assert (val == compared) is expected
    assert (compared == val) is expected


@pytest.mark.parametrize(
    ('values', 'expected'),
    (('bar', True), ('foo', False), (MISSING, False)),
)
def test_not_in(values, expected):
    compared = NotIn('baz', 'foo')
    assert (values == compared) is expected
    assert (compared == values) is expected


trivial_array_schema = Array(Map('foo', 'id'))


def test_validate_top_level_array_not_an_array():
    with pytest.raises(ValidationError) as excinfo:
        validate({}, trivial_array_schema)
    assert excinfo.value.error_msg == "Expected array but got 'dict'"


def test_validate_top_level_array_no_objects():
    with pytest.raises(ValidationError) as excinfo:
        validate([], trivial_array_schema)
    assert excinfo.value.error_msg == "Expected at least 1 'foo'"


@pytest.mark.parametrize('v', (({},), [{}]))
def test_ok_both_types(v):
    validate(v, trivial_array_schema)


map_required = Map('foo', 'key', Required('key', check_bool))
map_optional = Map('foo', 'key', Optional('key', check_bool, False))
map_no_default = Map('foo', 'key', OptionalNoDefault('key', check_bool))
map_no_id_key = Map('foo', None, Required('key', check_bool))


def test_map_wrong_type():
    with pytest.raises(ValidationError) as excinfo:
        validate([], map_required)
    assert excinfo.value.error_msg == 'Expected a foo map but got a list'


def test_required_missing_key():
    with pytest.raises(ValidationError) as excinfo:
        validate({}, map_required)
    expected = ('At foo(key=MISSING)', 'Missing required key: key')
    _assert_exception_trace(excinfo.value, expected)


@pytest.mark.parametrize(
    'schema', (map_required, map_optional, map_no_default),
)
def test_map_value_wrong_type(schema):
    with pytest.raises(ValidationError) as excinfo:
        validate({'key': 5}, schema)
    expected = ('At foo(key=5)', 'At key: key', 'Expected bool got int')
    _assert_exception_trace(excinfo.value, expected)


@pytest.mark.parametrize(
    'schema', (map_required, map_optional, map_no_default),
)
def test_map_value_correct_type(schema):
    validate({'key': True}, schema)


@pytest.mark.parametrize('schema', (map_optional, map_no_default))
def test_optional_key_missing(schema):
    validate({}, schema)


def test_error_message_no_id_key():
    with pytest.raises(ValidationError) as excinfo:
        validate({'key': 5}, map_no_id_key)
    expected = ('At foo()', 'At key: key', 'Expected bool got int')
    _assert_exception_trace(excinfo.value, expected)


map_conditional = Map(
    'foo', 'key',
    Conditional(
        'key2', check_bool, condition_key='key', condition_value=True,
    ),
)
map_conditional_not = Map(
    'foo', 'key',
    Conditional(
        'key2', check_bool, condition_key='key', condition_value=Not(False),
    ),
)
map_conditional_absent = Map(
    'foo', 'key',
    Conditional(
        'key2', check_bool,
        condition_key='key', condition_value=True, ensure_absent=True,
    ),
)
map_conditional_absent_not = Map(
    'foo', 'key',
    Conditional(
        'key2', check_bool,
        condition_key='key', condition_value=Not(True), ensure_absent=True,
    ),
)
map_conditional_absent_not_in = Map(
    'foo', 'key',
    Conditional(
        'key2', check_bool,
        condition_key='key', condition_value=NotIn(1, 2), ensure_absent=True,
    ),
)


@pytest.mark.parametrize('schema', (map_conditional, map_conditional_not))
@pytest.mark.parametrize(
    'v',
    (
        # Conditional check passes, key2 is checked and passes
        {'key': True, 'key2': True},
        # Conditional check fails, key2 is not checked
        {'key': False, 'key2': 'ohai'},
    ),
)
def test_ok_conditional_schemas(v, schema):
    validate(v, schema)


@pytest.mark.parametrize('schema', (map_conditional, map_conditional_not))
def test_not_ok_conditional_schemas(schema):
    with pytest.raises(ValidationError) as excinfo:
        validate({'key': True, 'key2': 5}, schema)
    expected = ('At foo(key=True)', 'At key: key2', 'Expected bool got int')
    _assert_exception_trace(excinfo.value, expected)


def test_ensure_absent_conditional():
    with pytest.raises(ValidationError) as excinfo:
        validate({'key': False, 'key2': True}, map_conditional_absent)
    expected = (
        'At foo(key=False)',
        'Expected key2 to be absent when key is not True, '
        'found key2: True',
    )
    _assert_exception_trace(excinfo.value, expected)


def test_ensure_absent_conditional_not():
    with pytest.raises(ValidationError) as excinfo:
        validate({'key': True, 'key2': True}, map_conditional_absent_not)
    expected = (
        'At foo(key=True)',
        'Expected key2 to be absent when key is True, '
        'found key2: True',
    )
    _assert_exception_trace(excinfo.value, expected)


def test_ensure_absent_conditional_not_in():
    with pytest.raises(ValidationError) as excinfo:
        validate({'key': 1, 'key2': True}, map_conditional_absent_not_in)
    expected = (
        'At foo(key=1)',
        'Expected key2 to be absent when key is any of (1, 2), '
        'found key2: True',
    )
    _assert_exception_trace(excinfo.value, expected)


def test_no_error_conditional_absent():
    validate({}, map_conditional_absent)
    validate({}, map_conditional_absent_not)
    validate({'key2': True}, map_conditional_absent)
    validate({'key2': True}, map_conditional_absent_not)


def test_apply_defaults_copies_object():
    val = {}
    ret = apply_defaults(val, map_optional)
    assert ret is not val


def test_apply_defaults_sets_default():
    ret = apply_defaults({}, map_optional)
    assert ret == {'key': False}


def test_apply_defaults_does_not_change_non_default():
    ret = apply_defaults({'key': True}, map_optional)
    assert ret == {'key': True}


def test_apply_defaults_does_nothing_on_non_optional():
    ret = apply_defaults({}, map_required)
    assert ret == {}


def test_apply_defaults_map_in_list():
    ret = apply_defaults([{}], Array(map_optional))
    assert ret == [{'key': False}]


def test_remove_defaults_copies_object():
    val = {'key': False}
    ret = remove_defaults(val, map_optional)
    assert ret is not val


def test_remove_defaults_removes_defaults():
    ret = remove_defaults({'key': False}, map_optional)
    assert ret == {}


def test_remove_defaults_nothing_to_remove():
    ret = remove_defaults({}, map_optional)
    assert ret == {}


def test_remove_defaults_does_not_change_non_default():
    ret = remove_defaults({'key': True}, map_optional)
    assert ret == {'key': True}


def test_remove_defaults_map_in_list():
    ret = remove_defaults([{'key': False}], Array(map_optional))
    assert ret == [{}]


def test_remove_defaults_does_nothing_on_non_optional():
    ret = remove_defaults({'key': True}, map_required)
    assert ret == {'key': True}


nested_schema_required = Map(
    'Repository', 'repo',
    Required('repo', check_any),
    RequiredRecurse('hooks', Array(map_required)),
)
nested_schema_optional = Map(
    'Repository', 'repo',
    Required('repo', check_any),
    RequiredRecurse('hooks', Array(map_optional)),
)


def test_validate_failure_nested():
    with pytest.raises(ValidationError) as excinfo:
        validate({'repo': 1, 'hooks': [{}]}, nested_schema_required)
    expected = (
        'At Repository(repo=1)',
        'At key: hooks',
        'At foo(key=MISSING)',
        'Missing required key: key',
    )
    _assert_exception_trace(excinfo.value, expected)


def test_apply_defaults_nested():
    val = {'repo': 'repo1', 'hooks': [{}]}
    ret = apply_defaults(val, nested_schema_optional)
    assert ret == {'repo': 'repo1', 'hooks': [{'key': False}]}


def test_remove_defaults_nested():
    val = {'repo': 'repo1', 'hooks': [{'key': False}]}
    ret = remove_defaults(val, nested_schema_optional)
    assert ret == {'repo': 'repo1', 'hooks': [{}]}


class Error(Exception):
    pass


def test_load_from_filename_file_does_not_exist():
    with pytest.raises(Error) as excinfo:
        load_from_filename('does_not_exist', map_required, json.loads, Error)
    assert excinfo.value.args[0].error_msg == 'does_not_exist does not exist'


def test_load_from_filename_fails_load_strategy(tmpdir):
    f = tmpdir.join('foo.notjson')
    f.write('totes not json')
    with pytest.raises(Error) as excinfo:
        load_from_filename(f.strpath, map_required, json.loads, Error)
    # ANY is json's error message
    expected = ('File {}'.format(f.strpath), mock.ANY)
    _assert_exception_trace(excinfo.value.args[0], expected)


def test_load_from_filename_validation_error(tmpdir):
    f = tmpdir.join('foo.json')
    f.write('{}')
    with pytest.raises(Error) as excinfo:
        load_from_filename(f.strpath, map_required, json.loads, Error)
    expected = (
        'File {}'.format(f.strpath),
        'At foo(key=MISSING)',
        'Missing required key: key',
    )
    _assert_exception_trace(excinfo.value.args[0], expected)


def test_load_from_filename_applies_defaults(tmpdir):
    f = tmpdir.join('foo.json')
    f.write('{}')
    ret = load_from_filename(f.strpath, map_optional, json.loads, Error)
    assert ret == {'key': False}