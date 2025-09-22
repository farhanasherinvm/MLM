from django_filters import FilterSet, ChoiceFilter, CharFilter
from django.db.models import Q, Value
from django.db.models.functions import Concat
from django.db.models.fields import CharField
from datetime import date, timedelta
from level.models import UserLevel

class PaymentFilter(FilterSet):
    status = ChoiceFilter(
        choices=UserLevel._meta.get_field('status').choices
    )
    date_filter = ChoiceFilter(
        method='filter_by_period',
        choices=(
            ('today', 'Today'),
            ('this_week', 'This Week'),
            ('this_month', 'This Month'),
            ('this_year', 'This Year'),
        )
    )
    search = CharFilter(method='filter_by_search', label='Search')

    def filter_by_period(self, queryset, name, value):
        today = date.today()

        if value == 'today':
            return queryset.filter(requested_date__date=today)
        elif value == 'this_week':
            start_date = today - timedelta(days=today.weekday())  # Start of this week (Monday)
            return queryset.filter(requested_date__date__gte=start_date, requested_date__date__lte=today)
        elif value == 'this_month':
            start_date = today.replace(day=1)
            return queryset.filter(requested_date__date__gte=start_date, requested_date__date__lte=today)
        elif value == 'this_year':
            start_date = today.replace(month=1, day=1)
            return queryset.filter(requested_date__date__gte=start_date, requested_date__date__lte=today)
        return queryset

    def filter_by_search(self, queryset, name, value):
        if not value:
            return queryset
        # Annotate only the current user's full name for searching
        queryset = queryset.annotate(
            from_user_full=Concat('user__first_name', Value(' '), 'user__last_name', output_field=CharField())
        )
        return queryset.filter(
            Q(user__user_id__icontains=value) |
            Q(level__name__icontains=value) |
            Q(from_user_full__icontains=value)
        ).distinct()

    class Meta:
        model = UserLevel
        fields = ['status', 'date_filter', 'search']