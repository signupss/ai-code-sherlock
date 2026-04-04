"""Пошаговый отладчик workflow."""
from datetime import datetime
from services.agent_models import AgentWorkflow, AgentNode

class WorkflowDebugger:
    """Step-by-step workflow executor for testing"""
    def __init__(self, workflow: AgentWorkflow, logger=None):
        self.workflow = workflow
        self.logger = logger
        self.current_node_id: str | None = None
        self.visited = set()
        self.path = []
        self.finished = False
        self.variables = {}
        
    def start(self):
        entry = self.workflow.get_entry_node()
        if entry:
            self.current_node_id = entry.id
            self.finished = False
            self.path = [entry.id]
            if self.logger:
                self.logger(f"▶️ Старт: {entry.name}")
            return entry
        return None
        
    def step(self) -> tuple[AgentNode | None, str]:
        """Execute one step"""
        if self.finished or not self.current_node_id:
            return None, "finished"
            
        current = self.workflow.get_node(self.current_node_id)
        if not current:
            return None, "error"
            
        self.visited.add(current.id)
        
        # Simulate execution
        if self.logger:
            self.logger(f"⏭️ Шаг: {current.name} ({current.agent_type.value})")
        
        # Find next node
        outgoing = self.workflow.get_outgoing_edges(current.id)
        if not outgoing:
            self.finished = True
            return current, "completed"
            
        next_edge = outgoing[0]  # Simple sequential
        self.current_node_id = next_edge.target_id
        self.path.append(self.current_node_id)
        
        return current, "running"
        
    def get_current(self) -> AgentNode | None:
        return self.workflow.get_node(self.current_node_id) if self.current_node_id else None
        
    def stop(self):
        self.finished = True
        if self.logger:
            self.logger("⏹️ Остановлено")
