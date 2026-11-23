from atlas.models.settings import SETTINGS_ROW_ID, StoredSettings
from atlas.repository.base import CrudRepository


class SettingsRepository(CrudRepository[StoredSettings]):
    model = StoredSettings

    async def load(self) -> StoredSettings:
        """The settings row, created with defaults on first run."""
        return await self.get(SETTINGS_ROW_ID) or await self.add(
            StoredSettings()
        )
