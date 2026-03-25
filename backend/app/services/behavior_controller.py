#------This Function handles behavior mode determination based on condition and confidence---------
def get_behavior_mode(condition_level: str, confidence_score: float) -> dict:
    """
    Determine behavior mode based on condition level and confidence score.
    
    Args:
        condition_level: str - one of ['low', 'mild', 'moderate', 'high']
        confidence_score: float - between 0.0 and 1.0
        
    Returns:
        dict: with keys 'repeat' (bool), 'urgency' (str), 'alert_caregiver' (bool)
    """
    # If confidence is less than 0.5, treat as mild regardless of condition
    if confidence_score < 0.5:
        condition_level = 'mild'
    
    # Define behavior based on condition level
    if condition_level == 'low':
        return {
            'repeat': False,
            'urgency': 'low',
            'alert_caregiver': False
        }
    elif condition_level == 'mild':
        return {
            'repeat': False,
            'urgency': 'normal',
            'alert_caregiver': False
        }
    elif condition_level == 'moderate':
        return {
            'repeat': True,
            'urgency': 'high',
            'alert_caregiver': False
        }
    elif condition_level == 'high':
        return {
            'repeat': True,
            'urgency': 'high',
            'alert_caregiver': True
        }
    else:
        # Default fallback
        return {
            'repeat': False,
            'urgency': 'normal',
            'alert_caregiver': False
        }