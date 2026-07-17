import json

from trainlab import __version__
from trainlab.openapi import main


def test_openapi_command_prints_the_runtime_contract(capsys) -> None:  # type: ignore[no-untyped-def]
    main()
    document = json.loads(capsys.readouterr().out)
    assert __version__ == "0.3.0"
    assert document["info"]["version"] == __version__
    assert "/api/v1/auth/login" in document["paths"]
