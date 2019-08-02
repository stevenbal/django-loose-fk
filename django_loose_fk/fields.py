from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from django.core import checks
from django.db import models
from django.db.models import Field
from django.db.models.base import ModelBase

from .loaders import RequestsLoader as Loader

InstanceOrUrl = Union[models.Model, str]


@dataclass
class FkOrURLField(models.Field):
    fk_field: str
    url_field: str
    verbose_name: Optional[str] = None
    help_text: Optional[str] = ""

    name = None

    # attributes that django.db.models.fields.Field normally set
    creation_counter = 0

    remote_field = None
    is_relation = False
    primary_key = False
    concrete = False
    column = None

    many_to_many = None
    null = False
    default = models.NOT_PROVIDED
    blank = False
    db_index = False
    serialize = True
    unique_for_date = None
    unique_for_month = None
    unique_for_year = None
    _validators = ()
    editable = True
    choices = ()

    def __post_init__(self):
        self.creation_counter = Field.creation_counter
        Field.creation_counter += 1

    def __lt__(self, other):
        # This is needed because bisect does not take a comparison function.
        if isinstance(other, Field):
            return self.creation_counter < other.creation_counter
        return NotImplemented

    def contribute_to_class(
        self, cls: ModelBase, name: str, private_only: bool = False
    ):
        """
        Register the field with the model class.
        """
        self.name = name
        self.model = cls

        cls._meta.add_field(self)

        # install the descriptor
        setattr(cls, self.name, FkOrURLDescriptor(self))

        # TODO: add hidden URLField to the model as well (virtual field)

    @property
    def _fk_field(self) -> models.ForeignKey:
        # get the actual fields - uses private API because the app registry isn't
        # ready yet
        # TODO: maybe it is now?
        _fields = {field.name: field for field in self.model._meta.fields}
        return _fields[self.fk_field]

    @property
    def _url_field(self) -> models.URLField:
        # get the actual fields - uses private API because the app registry isn't
        # ready yet
        # TODO: maybe it is now?
        _fields = {field.name: field for field in self.model._meta.fields}
        return _fields[self.url_field]

    def check(self, **kwargs) -> List[checks.Error]:
        errors = []
        if not isinstance(self._fk_field, models.ForeignKey):
            errors.append(
                checks.Error(
                    "The field passed to 'fk_field' should be a ForeignKey",
                    obj=self,
                    id="fk_or_url_field.E001",
                )
            )

        if not isinstance(self._url_field, models.URLField):
            errors.append(
                checks.Error(
                    "The field passed to 'url_field' should be a URLField",
                    obj=self,
                    id="fk_or_url_field.E002",
                )
            )

        # TODO: check for missing check constraint?

        return errors

    @property
    def attname(self) -> str:
        return self.name

    def get_attname_column(self) -> Tuple[str, None]:
        return self.attname, None

    def clone(self):
        """
        Uses deconstruct() to clone a new copy of this Field.
        Will not preserve any class attachments/attribute names.
        """
        name, path, args, kwargs = self.deconstruct()
        return self.__class__(*args, **kwargs)

    def deconstruct(self):
        path = "%s.%s" % (self.__class__.__module__, self.__class__.__qualname__)
        keywords = {
            "fk_field": self.fk_field,
            "url_field": self.url_field,
            "verbose_name": self.verbose_name,
            "help_text": self.help_text,
        }
        return (self.name, path, [], keywords)


@dataclass
class FkOrURLDescriptor:
    field: FkOrURLField

    @property
    def fk_field_name(self) -> str:
        return self.field._fk_field.name

    @property
    def url_field_name(self) -> str:
        return self.field._url_field.name

    def __get__(self, instance, cls=None):
        """
        Get the related instance through the forward relation.
        """
        # if the value is select_related, this will hit that cache
        fk_value = getattr(instance, self.fk_field_name)
        if fk_value is not None:
            return fk_value

        url_value = getattr(instance, self.url_field_name)
        if not url_value:
            raise ValueError("No FK value and no URL value, this is not allowed!")

        remote_model = self.field._fk_field.related_model
        remote_loader = Loader(url=url_value, model=remote_model)
        return remote_loader.load()

    def __set__(self, instance: models.Model, value: InstanceOrUrl):
        """
        Set the related instance through the forward relation.

        Delegate the set action to the appropriate field.
        """
        if isinstance(value, models.Model):
            field_name = self.fk_field_name
        elif isinstance(value, str):
            field_name = self.url_field_name
        else:
            raise TypeError(f"value is of type {type(value)}, which is not supported.")
        setattr(instance, field_name, value)