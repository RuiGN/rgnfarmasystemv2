from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _entries(name):
    return {
        line.strip().split('==')[0].casefold().replace('_', '-')
        for line in (ROOT / name).read_text().splitlines()
        if line.strip() and not line.startswith(('#', '-'))
    }


def test_runtime_manifest_declares_required_django_extensions():
    assert {'drf-spectacular', 'django-celery-beat'} <= _entries('requirements.txt')


def test_runtime_manifest_excludes_desktop_system_gpu_and_test_tools():
    entries = _entries('requirements.txt')
    forbidden = {
        'brlapi',
        'command-not-found',
        'python-apt',
        'cupshelpers',
        'dbus-python',
        'cuda-toolkit',
        'nvidia-nccl-cu13',
        'flet',
        'ufw',
        'pytest',
        'flake8',
        'pygount',
        'playwright',
        'yt-dlp',
    }
    assert not (entries & forbidden)


def test_development_manifest_declares_the_test_runner():
    assert {'pytest', 'pytest-django', 'pytest-cov'} <= _entries('requirements-dev.txt')


def test_pdf_parser_includes_the_audited_denial_of_service_fixes():
    from packaging.version import Version

    for manifest in ('requirements.in', 'requirements.txt'):
        version = next(
            line.split('==', 1)[1]
            for line in (ROOT / manifest).read_text().splitlines()
            if line.casefold().startswith('pypdf==')
        )
        assert Version(version) >= Version('6.20.1')
