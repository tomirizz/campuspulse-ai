import pytest

from campuspulse.provider_json import parse_json_response


@pytest.mark.parametrize("text", ['{"x":1}', ' \n {"x":1}\n ', '```json\n{"x":1}\n```', '```\r\n{"x":1}\r\n```'])
def test_only_whole_json_or_one_outer_code_fence_is_accepted(text):
    assert parse_json_response(text) == {"x": 1}


@pytest.mark.parametrize("text", ['', None, 'prefix {"x":1}', '{"x":1} suffix', '```js\n{"x":1}\n```', '```json\n{"x":1}\n```\nextra', '```json\n{"x":1}\n```\n```json\n{}\n```'])
def test_invalid_or_surrounded_json_is_rejected(text):
    with pytest.raises(ValueError):
        parse_json_response(text)


def test_response_size_bound_includes_surrounding_whitespace():
    with pytest.raises(ValueError):
        parse_json_response('  {"x":1}', max_chars=7)
