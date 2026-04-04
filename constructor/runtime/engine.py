"""Полноценный движок выполнения workflow."""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from services.agent_models import AgentWorkflow, AgentNode, AgentType, EdgeCondition

class WorkflowRuntimeEngine:
    """Полноценный движок выполнения workflow с автопатчингом и самоулучшением"""
    
    def __init__(self, workflow: AgentWorkflow, model_manager, skill_registry, logger_callback=None):
        self.workflow = workflow
        self.model_manager = model_manager
        self.skill_registry = skill_registry
        self.logger = logger_callback or print
        
        self.execution_context = {}  # Глобальный контекст выполнения
        self.node_states = {}        # Состояние каждого узла
        self.skill_cache = {}        # Кэш загруженных скиллов
        self.execution_history = []  # История для отката
        self.current_path = []       # Текущий путь выполнения
        
        self._paused = False
        self._current_node_id = None
        self._step_mode = False
    
    def _load_global_variables_to_context(self):
        """Загрузить глобальные переменные из метаданных workflow в контекст выполнения."""
        meta = getattr(self.workflow, 'metadata', {}) or {}
        if not isinstance(meta, dict):
            return
        gvars = meta.get('global_variables', [])
        global_dict = {}
        for gv in gvars:
            if isinstance(gv, dict) and gv.get('name'):
                global_dict[gv['name']] = gv.get('value', gv.get('default', ''))
        self.execution_context['__globals__'] = global_dict

    def get_global_variable(self, name: str, default=None):
        """Получить значение глобальной переменной."""
        return self.execution_context.get('__globals__', {}).get(name, default)

    def set_global_variable(self, name: str, value):
        """Установить значение глобальной переменной (доступно всем потокам через shared context)."""
        if '__globals__' not in self.execution_context:
            self.execution_context['__globals__'] = {}
        self.execution_context['__globals__'][name] = value
        # Синхронизируем обратно в metadata workflow
        meta = getattr(self.workflow, 'metadata', {}) or {}
        if not isinstance(meta, dict):
            meta = {}
        gvars = meta.get('global_variables', [])
        for gv in gvars:
            if isinstance(gv, dict) and gv.get('name') == name:
                gv['value'] = value
                break
        meta['global_variables'] = gvars
        self.workflow.metadata = meta
    
    async def execute_workflow(self, start_node_id: str = None, initial_input: dict = None):
        """Запуск workflow с полным контролем"""
        entry = self.workflow.get_node(start_node_id) if start_node_id else self.workflow.get_entry_node()
        if not entry:
            raise ValueError("No entry node found")
            
        self.execution_context["input"] = initial_input or {}
        self.execution_context["start_time"] = datetime.now().isoformat()
        
        current_node = entry
        iteration = 0
        
        while current_node and iteration < self.workflow.max_total_steps:
            if self._paused:
                await self._wait_for_resume()
                
            self._current_node_id = current_node.id
            self.current_path.append(current_node.id)
            
            try:
                # Проверка breakpoint
                if current_node.breakpoint_enabled or self._step_mode:
                    await self._trigger_breakpoint(current_node)
                
                # Автоподбор скиллов если включен
                if current_node.auto_load_skills:
                    await self._load_dynamic_skills(current_node)
                
                # Выполнение узла с ретраями и патчингом
                result = await self._execute_node_with_recovery(current_node)
                
                # Валидация результата
                if not self._validate_output(current_node, result):
                    if current_node.auto_patch:
                        result = await self._attempt_patch(current_node, result)
                    else:
                        raise ValueError(f"Validation failed for {current_node.name}")
                
                # Сохранение состояния
                self.node_states[current_node.id] = {
                    "status": "success",
                    "output": result,
                    "timestamp": datetime.now().isoformat()
                }
                
                # Определение следующего узла
                next_node = await self._determine_next_node(current_node, result)
                
                # Если есть fallback и ошибка - переключаемся
                if result.get("_fallback_triggered") and current_node.fallback_agent_id:
                    next_node = self.workflow.get_node(current_node.fallback_agent_id)
                
                current_node = next_node
                iteration += 1
                
            except Exception as e:
                self.logger(f"❌ Ошибка в {current_node.name}: {e}")
                if current_node.fallback_agent_id:
                    current_node = self.workflow.get_node(current_node.fallback_agent_id)
                else:
                    raise
        
        return self.execution_context
    
    async def _execute_node_with_recovery(self, node: AgentNode):
        """Выполнение с повторами и самоисправлением"""
        last_error = None
        
        for attempt in range(node.retry_count + 1):
            try:
                # Выбор модели под задачу
                model_id = self._select_model_for_task(node)
                provider = self.model_manager.get_provider(model_id)
                
                # Формирование промпта со скиллами
                prompt = self._build_enhanced_prompt(node)
                
                # Выполнение с таймаутом
                result = await asyncio.wait_for(
                    self._run_agent(node, provider, prompt),
                    timeout=node.timeout_seconds
                )
                
                # Автотест если включен
                if node.auto_test and not await self._run_auto_test(node, result):
                    raise ValueError("Auto-test failed")
                
                return result
                
            except Exception as e:
                last_error = str(e)
                self.logger(f"⚠️ Попытка {attempt + 1} не удалась: {e}")
                
                if node.auto_improve and attempt < node.retry_count:
                    # Автоулучшение промпта на основе ошибки
                    node.system_prompt = await self._improve_prompt(node, e)
                
                await asyncio.sleep(2 ** attempt if node.backoff_strategy == "exponential" else 2)
        
        raise RuntimeError(f"Все попытки исчерпаны: {last_error}")
    
    async def _load_dynamic_skills(self, node: AgentNode):
        """Использует LLM для выбора релевантных скиллов из базы"""
        if not node.skill_analysis_model_id:
            return
            
        all_skills = self.skill_registry.all_skills()
        task_desc = f"{node.name}: {node.description}"
        
        # Запрос к модели для ранжирования скиллов
        prompt = f"""Task: {task_desc}
Available skills: {[f"{s.id}: {s.name}" for s in all_skills]}
Select relevant skill IDs (comma separated) or 'none':"""
        
        provider = self.model_manager.get_provider(node.skill_analysis_model_id)
        response = await provider.complete(prompt)
        
        selected_ids = [s.strip() for s in response.split(",") if s.strip() != "none"]
        
        # Добавляем выбранные скиллы к агенту
        for sid in selected_ids:
            if sid not in node.skill_ids:
                skill = self.skill_registry.get(sid)
                if skill:
                    node.skill_ids.append(sid)
                    self.logger(f"🔧 Автоподгружен скилл: {skill.name}")
    
    async def _attempt_patch(self, node: AgentNode, failed_result: dict):
        """Автоматический патчинг кода при ошибке"""
        if not node.patch_target_files:
            return failed_result
        
        self.logger(f"🔧 Попытка патчинга для {node.name}...")
        
        # Анализ ошибки и генерация патча
        patch_agent = AgentNode(
            name="AutoPatcher",
            agent_type=AgentType.CODE_WRITER,
            system_prompt="You are an automated patching system. Fix the code based on error logs."
        )
        
        # Применение патча к файлам
        for file_path in node.patch_target_files:
            if Path(file_path).exists():
                # Здесь логика применения патча из PatchEngine
                pass
        
        # Повторное выполнение
        return await self._execute_node_with_recovery(node)
    
    def _select_model_for_task(self, node: AgentNode) -> str:
        """Умный выбор модели под тип задачи"""
        if node.vision_model_id and any(t in ["vision", "image"] for t in node.available_tools):
            return node.vision_model_id
        if node.reasoning_model_id and len(node.system_prompt) > 2000:
            return node.reasoning_model_id
        if node.fast_model_id and node.agent_type in [AgentType.FILE_MANAGER, AgentType.SCRIPT_RUNNER]:
            return node.fast_model_id
        return node.model_id or "default"
    
    async def _determine_next_node(self, current: AgentNode, result: dict) -> Optional[AgentNode]:
        """Определение следующего шага с поддержкой LLM-routing"""
        if current.orchestration_mode == "llm_router":
            # LLM решает куда идти дальше
            options = self.workflow.get_outgoing_edges(current.id)
            if not options:
                return None
                
            prompt = f"""Current task: {current.name}
Result: {result}
Available next steps: {[self.workflow.get_node(e.target_id).name for e in options]}
Which one should execute next? Return exact node name or 'end':"""
            
            provider = self.model_manager.get_provider(current.reasoning_model_id or current.model_id)
            decision = await provider.complete(prompt)
            
            if decision.strip().lower() == 'end':
                return None
                
            # Поиск узла по имени
            for edge in options:
                node = self.workflow.get_node(edge.target_id)
                if node.name.lower() in decision.lower():
                    return node
        
        elif current.orchestration_mode == "conditional":
            # Условные переходы
            for branch in current.conditional_branches:
                # Передаем EdgeCondition в область видимости eval, чтобы условия вида "EdgeCondition.ON_FAILURE" вычислялись успешно
                if eval(branch["condition"], {"result": result, "context": self.execution_context, "EdgeCondition": EdgeCondition}):
                    return self.workflow.get_node(branch["target"])
        
        # Static mode - просто следующий по графу
        edges = self.workflow.get_outgoing_edges(current.id)
        return self.workflow.get_node(edges[0].target_id) if edges else None
    
    async def pause(self):
        self._paused = True
        
    async def resume(self):
        self._paused = False
        
    async def step(self):
        """Один шаг (для пошаговой отладки)"""
        self._step_mode = True
        self._paused = False
        await asyncio.sleep(0.1)  # Дать циклу выполниться
        self._step_mode = False
        self._paused = True
