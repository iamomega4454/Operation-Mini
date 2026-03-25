import logging
import asyncio
from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from beanie import init_beanie
from app.core.config import settings
from app.db.aura_modules import AuraModulesDB
from app.db.aura_events import AuraEventsDB

logger = logging.getLogger(__name__)

_client = None
_aura_modules_db = None
_aura_events_db = None


MAX_RETRIES = 3
RETRY_DELAY = 2
CONNECTION_TIMEOUT = 10
MAX_POOL_SIZE = 50
MIN_POOL_SIZE = 10


#------This Function handles the database connection---------
async def connect_db():
    global _client, _aura_modules_db, _aura_events_db
    
    retry_count = 0
    last_error = None
    
    while retry_count < MAX_RETRIES:
        try:
            logger.info(f"Attempting database connection (attempt {retry_count + 1}/{MAX_RETRIES})...")
            
            _client = AsyncMongoClient(
                settings.mongodb_uri,
                maxPoolSize=MAX_POOL_SIZE,
                minPoolSize=MIN_POOL_SIZE,
                connectTimeoutMS=CONNECTION_TIMEOUT * 1000,
                serverSelectionTimeoutMS=CONNECTION_TIMEOUT * 1000,
                retryWrites=True,
            )
            
            
            await _client.admin.command('ping')
            logger.info("Database connection established successfully")
            break
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            last_error = e
            retry_count += 1
            logger.warning(f"Database connection attempt {retry_count} failed: {str(e)}")
            
            if retry_count < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * retry_count)
            else:
                logger.error(f"Failed to connect to database after {MAX_RETRIES} attempts")
                raise RuntimeError(f"Failed to connect to database: {str(last_error)}")
        except Exception as e:
            logger.error(f"Unexpected error during database connection: {str(e)}")
            raise

    
    from app.models.user import User
    from app.models.medication import Medication
    from app.models.journal import JournalEntry
    from app.models.relative import Relative
    from app.models.sos import SOSEvent
    from app.models.settings import UserSettings
    from app.models.suggestion import Suggestion, SuggestionHistory
    from app.models.orito_interaction import OritoInteraction
    from app.models.reminder import Reminder
    from app.models.assessment import PatientAssessment, CaregiverAssessment, PatientProfile

    await init_beanie(
        database=_client[settings.db_name],
        document_models=[
            User,
            Medication,
            JournalEntry,
            Relative,
            SOSEvent,
            UserSettings,
            Suggestion,
            SuggestionHistory,
            OritoInteraction,
            Reminder,
            PatientAssessment,
            CaregiverAssessment,
            PatientProfile,
        ],
    )

    
    db = _client[settings.db_name]
    _aura_modules_db = AuraModulesDB(db)
    _aura_events_db = AuraEventsDB(db)

    
    await _aura_modules_db.ensure_indexes()
    await _aura_events_db.ensure_indexes()
    
    logger.info("Database initialization completed")


#------This Function closes the database connection---------
async def close_db():
    global _client
    if _client:
        try:
            await _client.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database connection: {str(e)}")


#------This Function returns the Aura modules database instance---------
def get_aura_modules_db() -> AuraModulesDB:
    if _aura_modules_db is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")
    return _aura_modules_db


#------This Function returns the Aura events database instance---------
def get_aura_events_db() -> AuraEventsDB:
    if _aura_events_db is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")
    return _aura_events_db


#------This Function checks the database health status---------
async def check_db_health() -> dict:
    try:
        if _client is None:
            return {"status": "unhealthy", "error": "Database not initialized"}
        
        await _client.admin.command('ping')
        return {"status": "healthy", "database": settings.db_name}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
