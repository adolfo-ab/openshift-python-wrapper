# This test uses https://github.com/RedHatQE/openshift-resources-definitions to get resource definitions json file
# File: resources_definitions.json

import ast
import json
import os
from typing import Any, Dict, Generator, List, Tuple

import pytest

from ocp_resources.resource import Resource  # noqa


def _api_group_name(api_value: str) -> str:
    try:
        return eval(f"Resource.ApiGroup.{api_value}")
    except AttributeError:
        return api_value


def _api_group_dict(resource_dict: Dict[str, Any], api_group_name: str) -> Dict[str, Any]:
    resource_dict_api_group = resource_dict["api_group"]
    api_group = resource_dict_api_group.get(api_group_name)
    if not api_group:
        try:
            api_group = resource_dict_api_group["null"]
        except KeyError:
            api_group = resource_dict_api_group[[*resource_dict_api_group][0]]

    return api_group


def _process_api_type(api_type: str, api_value: str, resource_dict, cls: ast.ClassDef) -> List[str]:
    if api_type == "api_group":
        return _get_api_group(
            api_value=api_value,
            cls=cls,
            resource_dict=resource_dict,
        )

    if api_type == "api_version":
        return _get_api_version(
            api_value=api_value,
            cls=cls,
            resource_dict=resource_dict,
        )

    return [f"Resource {cls.name} must have api_group or api_version"]


def _get_api_group_and_version(bodies: List[Any]) -> Tuple[str, str]:
    for targets in bodies:
        targets: ast.AnnAssign | ast.Attribute
        if isinstance(targets, ast.AnnAssign):
            api_type = targets.target.id
        else:
            api_type = targets.targets[0].id

        return api_type, getattr(targets.value, "attr", getattr(targets.value, "value", None))

    return "", ""


def _get_namespaced(cls: ast.ClassDef, resource_dict: Dict[str, Any], api_value: str) -> List[str]:
    errors = []
    for base in getattr(cls, "bases", []):
        api_group_name = _api_group_name(api_value=api_value)
        namespaced = base.id == "NamespacedResource"
        api_group = _api_group_dict(resource_dict=resource_dict, api_group_name=api_group_name)
        should_be_namespaced = api_group["namespaced"] == "true"

        if namespaced != should_be_namespaced:
            errors.append(
                f"Resource {cls.name} should be "
                f"{'namespaced' if should_be_namespaced else 'in cluster scope (not namespaced)'}"
            )
    return errors


def _get_api_group(api_value: str, cls: ast.ClassDef, resource_dict: Dict[str, Any]) -> List[str]:
    errors = []
    api_group_name = _api_group_name(api_value=api_value)

    if api_group_name not in resource_dict["api_group"]:
        errors.append(f"Resource {cls.name} api_group should be {resource_dict['api_group']}. got {api_group_name}")
    return errors


def _get_api_version(api_value: str, cls: ast.ClassDef, resource_dict: Dict[str, Any]) -> List[str]:
    errors = []
    api_group_name = _api_group_name(api_value=api_value)
    api_group = _api_group_dict(resource_dict=resource_dict, api_group_name=api_group_name)
    if api_value.lower() != api_group["api_version"]:
        desire_api_group = resource_dict["api_version"].split("/")[0]
        errors.append(
            f"Resource {cls.name} have api_version {api_value} but should have api_group = {desire_api_group}"
        )

    return errors


def _resource_file() -> Generator[str, None, None]:
    ocp_resources_exclude_files = ["resource.py", "utils.py", "__init__.py"]
    for root, _, files in os.walk("ocp_resources"):
        for _file in files:
            if _file in ocp_resources_exclude_files or not _file.endswith(".py"):
                continue

            yield os.path.join(root, _file)


@pytest.fixture()
def resources_definitions() -> Generator[Dict[str, Any], None, None]:
    with open("tests/scripts/resources_definitions.json") as fd:
        yield json.load(fd)


@pytest.fixture()
def resources_definitions_errors(resources_definitions: Dict[str, Any]) -> List[str]:
    errors = []
    for _file in _resource_file():
        with open(_file, "r") as fd:
            tree = ast.parse(source=fd.read())
            classes = [cls for cls in tree.body if isinstance(cls, ast.ClassDef)]
            for cls in classes:
                resource_dict = resources_definitions.get(cls.name)
                if not resource_dict:
                    # TODO: Fail and let the user know that 'tests/scripts/resources_definitions.json'
                    #   need to be updated using 'update_resources_definitions' script
                    continue

                bodies = [body_ for body_ in getattr(cls, "body") if isinstance(body_, (ast.Assign, ast.AnnAssign))]
                api_type, api_value = _get_api_group_and_version(bodies=bodies)
                errors.extend(_get_namespaced(cls=cls, resource_dict=resource_dict, api_value=api_value))
                errors.extend(
                    _process_api_type(
                        api_type=api_type,
                        api_value=api_value,
                        resource_dict=resource_dict,
                        cls=cls,
                    )
                )
    return errors


def test_resources_definitions(resources_definitions_errors):
    assert not resources_definitions_errors, "\n".join(resources_definitions_errors)
