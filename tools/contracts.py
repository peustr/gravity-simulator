"""Compare values executed by Godot with the physics implementation."""
import numpy as np

import server
import world


def check(data):
    assert data['keys'] == list(world.TYPE_KEYS)
    assert data['protocol'] == server.PROTOCOL_VERSION
    assert data['kinds'] == [server.STATE_KIND, server.PREDICTION_KIND]
    assert data['port'] == server.DEFAULT_PORT
    assert data['layout'] == [server.HEADER_FLOATS, server.BODY_FLOATS, server.EVENT_FLOATS]
    assert data['presets'] == list(world.SCENARIOS)
    expected_ids = {key.upper(): value for key, value in world.TYPE_KEYS.items()}
    expected_ids.update({key: value for key, value in vars(world).items() if key.startswith('EV_')})
    assert data['ids'] == expected_ids
    np.testing.assert_allclose(data['masses'], list(world.DEFAULT_MASS.values()), rtol=1e-7)
    # Artistic mesh sizes are not a physics/protocol contract. Validate their
    # shape and ordering; authoritative contact radii arrive in state packets.
    for row in data['radii']:
        assert len(row) == len(data['samples'])
        assert np.isfinite(row).all() and np.all(np.asarray(row) > 0)
        assert np.all(np.diff(row) >= 0)
    assert len(data['radii']) == len(world.TYPE_KEYS)
    print('Python/Godot contract checks PASSED')
