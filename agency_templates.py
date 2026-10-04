"""Local reusable campaign settings, separate from projects and source files."""
import copy
import json
from pathlib import Path
import re
import uuid
from agency_projects import validate_profile
from settings import get_app_data_dir
from studio_runtime import StagedOutput

TEMPLATE_FIELDS = ('client', 'colors', 'fonts', 'logo', 'watermark', 'naming', 'preset', 'export_set', 'settings', 'delivery_rules')


def templates_dir():
    directory = get_app_data_dir() / 'agency-templates'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_template(name, profile, package=True, directory=None):
    name = str(name).strip()
    if not name or len(name) > 100:
        raise ValueError('Enter a template name of 1–100 characters')
    validate_profile(profile)
    if profile.get('export_set','Single preset')=='Single preset' and profile.get('preset')=='Current queue settings':
        raise ValueError('Choose an explicit delivery preset before saving a campaign template')
    settings = copy.deepcopy({key: profile[key] for key in TEMPLATE_FIELDS if key in profile})
    identifier = uuid.uuid4().hex
    template = {'version': 1, 'id': identifier, 'name': name, 'package': bool(package), 'profile': settings}
    destination = (directory or templates_dir()) / (identifier + '.json')
    with StagedOutput(destination) as stage:
        stage.path.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding='utf-8')
    return stage.output


def load_template(path):
    template = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(template, dict) or template.get('version') != 1 or not re.fullmatch(r'[a-f0-9]{32}', str(template.get('id', ''))) or not isinstance(template.get('name'), str) or not 1 <= len(template['name'].strip()) <= 100 or type(template.get('package')) is not bool or not isinstance(template.get('profile'), dict):
        raise ValueError('Invalid campaign template')
    template['profile'] = {key: value for key, value in template['profile'].items() if key in TEMPLATE_FIELDS}
    validate_profile({**template['profile'], 'project': 'Template'})
    return template


def instantiate_template(template, project=''):
    profile = copy.deepcopy(template['profile'])
    validate_profile({**profile, 'project': 'Template'})
    profile['project'] = project
    return profile


def list_templates():
    templates = []
    for path in templates_dir().glob('*.json'):
        try:
            templates.append((path, load_template(path)))
        except (OSError, ValueError, TypeError):
            continue
    return sorted(templates, key=lambda item: (item[1]['name'].casefold(), item[1]['id']))
