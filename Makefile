.PHONY: test task1 task2-downstream task2 task3-provider task3 task4-primary task4-secondary task4

test:
	pytest -q

task1:
	python -m task1_mcp_server.server

task2-downstream:
	uvicorn task2_mcp_gateway.mock_downstream:app --port 9001

task2:
	uvicorn task2_mcp_gateway.app:app --port 8002

task3-provider:
	uvicorn task3_llm_guardrail.mock_provider:app --port 9002

task3:
	uvicorn task3_llm_guardrail.app:app --port 8003

task4-primary:
	uvicorn task4_model_router.mock_primary:app --port 9003

task4-secondary:
	uvicorn task4_model_router.mock_secondary:app --port 9004

task4:
	uvicorn task4_model_router.app:app --port 8004
