from django.core.management.base import BaseCommand
from django.db import transaction
from mtaa import tanzania
from config.api.models import Location
class Command(BaseCommand):
    help='Import mtaa 1.5 in bounded batches; preserve existing IDs and custom entries.'
    @transaction.atomic
    def handle(self,**options):
        existing={x.identity:x for x in Location.objects.filter(source='mtaa-1.5')}
        levels=['region','district','ward','street','local'];containers=['districts','wards','streets']
        nodes=[(None,tanzania.tree())];count=0
        for depth,level in enumerate(levels):
            next_nodes=[];new=[];pairs=[];seen=set()
            for parent,data in nodes:
                if isinstance(data,list):data={x:{} for x in data if isinstance(x,str) and x.strip()}
                if not isinstance(data,dict):continue
                for source,children in data.items():
                    if 'post_code' in source or not source.strip():continue
                    name=' '.join(source.split());norm=''.join(c for c in name.casefold() if c.isalnum())
                    identity=f'mtaa:{parent.pk if parent else 0}:{level}:{norm}'
                    if identity in seen:continue
                    seen.add(identity)
                    obj=existing.get(identity)
                    if not obj:
                        obj=Location(identity=identity,name=name,normalized_name=norm,source_name=source,source='mtaa-1.5',parent=parent,level=level)
                        new.append(obj)
                    if depth<3 and isinstance(children,dict):children=children.get(containers[depth],{})
                    pairs.append((obj,children));count+=1
            Location.objects.bulk_create(new,batch_size=500)
            nodes=pairs
        self.stdout.write(self.style.SUCCESS(f'Imported/verified {count} locations. Dataset coverage is not guaranteed current or complete.'))
