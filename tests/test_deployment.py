"""Regression checks for portable paths and exporting credential-free local bundles."""
import importlib.util
from pathlib import Path

import pytest


def load_script(name):
    path = Path(__file__).resolve().parents[1] / 'scripts' / name
    spec = importlib.util.spec_from_file_location('deployment_test_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/private', 'work/policy.db', '.env',
                                 '.env.local', '.workbuddy/mcp.json', 'project.private.config.json',
                                 'models/../.env', 'node_modules/x', 'x\\..\\secret'])
def test_export_rejects_private_files_and_escaping_paths(name):
    with pytest.raises(ValueError):
        load_script('prepare_local_deployment.py').relative_path(name)


def test_parent_directory_argument_can_read_existing_file(tmp_path):
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'marker.txt').write_text('portable', encoding='utf-8')
    for name in ['prepare_local_deployment.py', 'verify_deployment_bundle.py', 'verify_local_deployment.py']:
        path = load_script(name).io_path(tmp_path / 'sub' / '..' / 'marker.txt')
        assert path.read_text(encoding='utf-8') == 'portable'


def test_secret_scanning_rejects_values_across_chunk_boundaries(tmp_path):
    value = b'fictional-secret-for-export-regression'
    path = tmp_path / 'fixture.bin'
    path.write_bytes(b'x' * (1024 * 1024 - 4) + value + b'tail')
    with pytest.raises(ValueError) as caught:
        load_script('prepare_local_deployment.py').scan_file(path, [value])
    assert value.decode() not in str(caught.value)


def test_build_does_not_replace_existing_deployment_directory(tmp_path):
    destination = tmp_path / 'existing'
    destination.mkdir()
    marker = destination / 'marker.txt'
    marker.write_text('keep', encoding='utf-8')
    with pytest.raises(ValueError, match='existing files will not be replaced'):
        load_script('prepare_local_deployment.py').build(tmp_path / 'unused.zip', destination, tmp_path / 'unused-output.zip')
    assert marker.read_text(encoding='utf-8') == 'keep'
