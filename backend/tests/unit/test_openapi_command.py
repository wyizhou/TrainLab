import json

from trainlab.openapi import main


def test_openapi_command_prints_the_runtime_contract(capsys) -> None:  # type: ignore[no-untyped-def]
    main()
    document = json.loads(capsys.readouterr().out)
    assert document["info"]["version"] == "0.1.0"
    assert "/api/v1/auth/login" in document["paths"]
