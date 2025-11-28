from django.db import models
from django.utils import timezone
import uuid

class TimeStampedModel(models.Model):
    """Abstract base model with created and updated timestamps"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True

class SoftDeleteModel(TimeStampedModel):
    """Abstract base model for soft deletion"""
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    
    def soft_delete(self):
        self.is_active = False
        self.deleted_at = timezone.now()
        self.save()
    
    class Meta:
        abstract = True