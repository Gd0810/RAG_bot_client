"""
AI Department Categorization Service
Uses the NVIDIA LLM API to classify an unresolved visitor request query into one of the active departments.
"""
import logging
from ..models import Department
from . import llm_client

logger = logging.getLogger(__name__)


def categorize_query(query_text: str) -> Department:
    """
    Categorizes the visitor query into an active Department.
    Falls back to 'General' department if classification fails or is ambiguous.
    """
    active_departments = list(Department.objects.filter(is_active=True))
    if not active_departments:
        # If no departments exist yet, return None
        return None

    dept_map = {d.department_name.lower(): d for d in active_departments}
    dept_names = [d.department_name for d in active_departments]

    # Find General department or fallback department object
    general_dept = dept_map.get("general")
    if not general_dept:
        general_dept = active_departments[0]

    if not query_text or not query_text.strip():
        return general_dept

    # Fast keyword check before calling LLM
    query_lower = query_text.lower()
    for name_lower, dept_obj in dept_map.items():
        if name_lower in query_lower and name_lower != "general":
            logger.info("Fast keyword categorized query '%s' to department '%s'", query_text, dept_obj.department_name)
            return dept_obj

    # AI Classification using NVIDIA LLM
    system_prompt = (
        "You are an AI department router for a college system. "
        "Classify the given user query into EXACTLY ONE department from the provided list of department names. "
        "Rules:\n"
        "1. Output ONLY the exact department name from the provided list, nothing else.\n"
        "2. Do not include quotes, markdown formatting, punctuation, or extra words.\n"
        "3. If the query does not clearly fit a specific department, output 'General'."
    )
    user_prompt = (
        f"Available Departments: {', '.join(dept_names)}\n\n"
        f"User Query: {query_text}\n\n"
        "Selected Department:"
    )

    try:
        result = llm_client.generate_answer(system_prompt, user_prompt)
        raw_answer = (result.get("answer") or "").strip().strip("'\"`.")
        raw_lower = raw_answer.lower()

        # Check exact or partial match with active department names
        if raw_lower in dept_map:
            matched_dept = dept_map[raw_lower]
            logger.info("AI categorized query '%s' to department '%s'", query_text, matched_dept.department_name)
            return matched_dept

        for name_lower, dept_obj in dept_map.items():
            if name_lower in raw_lower or raw_lower in name_lower:
                logger.info("AI partially categorized query '%s' to department '%s'", query_text, dept_obj.department_name)
                return dept_obj

    except Exception as e:
        logger.warning("AI categorization failed for query '%s': %s", query_text, e)

    return general_dept
