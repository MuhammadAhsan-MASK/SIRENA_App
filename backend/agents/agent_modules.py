class BaseAgent:
    def __init__(self, name: str):
        self.name = name

    async def run(self, input_data: dict) -> dict:
        """
        To be implemented by the partner.
        Returns a dict with 'trace' (summary message) and 'data' (structured output).
        """
        return {
            "trace": f"{self.name} processed data.",
            "data": {}
        }

class SignalAgent(BaseAgent):
    def __init__(self):
        super().__init__("Signal Ingestion Agent")

class DetectionAgent(BaseAgent):
    def __init__(self):
        super().__init__("Event Detection Agent")

class SeverityAgent(BaseAgent):
    def __init__(self):
        super().__init__("Severity Analysis Agent")

class PlanningAgent(BaseAgent):
    def __init__(self):
        super().__init__("Response Planning Agent")

class ExecutionAgent(BaseAgent):
    def __init__(self):
        super().__init__("Execution Simulation Agent")

class OutcomeAgent(BaseAgent):
    def __init__(self):
        super().__init__("Outcome Reporting Agent")
