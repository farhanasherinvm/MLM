from django_filters import rest_framework as filters
from level.models import UserLevel
from datetime import date, timedelta, datetime

class PaymentFilter(filters.FilterSet):
    status = filters.ChoiceFilter(
        choices=UserLevel._meta.get_field('status').choices
    )
    date_filter = filters.ChoiceFilter(
        method='filter_by_period',
        choices=(
            ('today', 'Today'),
            ('this_week', 'This Week'),  # Changed from last_week to this_week
            ('this_month', 'This Month'),  # Changed from last_month to this_month
            ('this_year', 'This Year'),
        )
    )
    search = filters.CharFilter(method='filter_by_search', label='Search')

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
        return queryset.filter(
            Q(user__email__icontains=value) |
            Q(user__user_id__icontains=value) |
            Q(level__name__icontains=value) |
            Q(status__icontains=value)
        )

    class Meta:
        model = UserLevel
        fields = ['status', 'date_filter', 'search']