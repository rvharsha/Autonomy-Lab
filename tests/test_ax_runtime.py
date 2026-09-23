"""AX serialization checks; actual lifecycle outcomes are recorded separately."""

import json

import yaml

from autonomy_lab.ax_runtime import ResourceLoader


def test_ax_resource_timestamp_stays_exact_and_json_serializable():
    text = 'metadata:\n  creationTimestamp: 2026-09-23T15:48:03.767139843Z\nspec:\n  suspend: false\n'
    resource = yaml.load(text, Loader=ResourceLoader)
    assert resource['metadata']['creationTimestamp'] == '2026-09-23T15:48:03.767139843Z'
    assert resource['spec']['suspend'] is False
    assert json.loads(json.dumps(resource)) == resource
